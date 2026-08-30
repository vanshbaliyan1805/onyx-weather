"""
Open-Meteo connector - authoritative current weather for Indian cities.

Why this source matters
-----------------------
Every other connector in this pipeline collects what *people say* about the
weather. This one collects what the weather *actually is*, from a numerical
weather model, for all ~55 cities in config.INDIAN_CITIES.

That gives the project two things:

1. Guaranteed data volume. No API key, no signup, no approval, no rate-limit
   cliff - it returns a full set of rows on every single run. Unlike social
   sources, it cannot come back empty.

2. Ground truth for fake-report detection. The ML teammate can join a social
   report's (city, timestamp) against the observed conditions here. A post
   claiming "streets flooded in Jaipur" when measured precipitation in Jaipur
   is 0.0 mm is a strong misinformation signal. This is the column that makes
   verification possible rather than guesswork.

API: https://api.open-meteo.com/v1/forecast  (free for non-commercial use)
Docs: https://open-meteo.com/en/docs
"""

import json
import os
from datetime import datetime, timedelta, timezone

from config import (
    OPENMETEO_ENDPOINT,
    OPENMETEO_CURRENT_VARS,
    OPENMETEO_BATCH_SIZE,
    OPENMETEO_THRESHOLDS,
    INDIAN_CITIES,
    SAMPLE_DATA_DIR,
)

SOURCE_NAME = "openmeteo"

# WMO weather interpretation codes -> (human label, our event category).
# Reference: https://open-meteo.com/en/docs (WMO Weather interpretation codes)
WMO_CODES = {
    0:  ("clear sky", "other"),
    1:  ("mainly clear", "other"),
    2:  ("partly cloudy", "other"),
    3:  ("overcast", "other"),
    45: ("fog", "fog"),
    48: ("depositing rime fog", "fog"),
    51: ("light drizzle", "rainfall"),
    53: ("moderate drizzle", "rainfall"),
    55: ("dense drizzle", "rainfall"),
    56: ("light freezing drizzle", "rainfall"),
    57: ("dense freezing drizzle", "rainfall"),
    61: ("slight rain", "rainfall"),
    63: ("moderate rain", "rainfall"),
    65: ("heavy rain", "rainfall"),
    66: ("light freezing rain", "rainfall"),
    67: ("heavy freezing rain", "rainfall"),
    71: ("slight snowfall", "other"),
    73: ("moderate snowfall", "other"),
    75: ("heavy snowfall", "other"),
    77: ("snow grains", "other"),
    80: ("slight rain showers", "rainfall"),
    81: ("moderate rain showers", "rainfall"),
    82: ("violent rain showers", "flooding"),
    85: ("slight snow showers", "other"),
    86: ("heavy snow showers", "other"),
    95: ("thunderstorm", "thunderstorm"),
    96: ("thunderstorm with slight hail", "thunderstorm"),
    99: ("thunderstorm with heavy hail", "thunderstorm"),
}


def _classify(current: dict) -> tuple:
    """
    Derive (event_category, human_summary) from measured values.

    Threshold checks run BEFORE the WMO code lookup, because a measured
    45 km/h gust or 42 C reading is a more specific signal than the model's
    general "partly cloudy" code. First match wins, most severe first.
    """
    t = OPENMETEO_THRESHOLDS
    temp = current.get("temperature_2m")
    precip = current.get("precipitation") or 0.0
    gusts = current.get("wind_gusts_10m") or 0.0
    wind = current.get("wind_speed_10m") or 0.0
    visibility = current.get("visibility")
    code = current.get("weather_code")

    code_label, code_category = WMO_CODES.get(code, ("unknown conditions", "other"))

    if precip >= t["very_heavy_rain_mm"]:
        return "flooding", f"very heavy rainfall ({precip} mm) - flooding risk"
    if precip >= t["heavy_rain_mm"]:
        return "rainfall", f"heavy rainfall ({precip} mm)"
    if temp is not None and temp >= t["heatwave_temp_c"]:
        return "heatwave", f"extreme heat ({temp} C)"
    if max(gusts, wind) >= t["strong_wind_kmh"]:
        return "strong_wind", f"strong winds (gusts {gusts} km/h)"
    if visibility is not None and visibility <= t["low_visibility_m"]:
        return "fog", f"low visibility ({visibility} m)"

    # No threshold breached - fall back to whatever the model's code says.
    return code_category, code_label


def _observed_at_utc(current: dict, block: dict) -> str:
    """
    Return the observation time as ISO-8601 WITH an explicit UTC offset.

    Open-Meteo honours the `timezone` request parameter and returns
    current["time"] as a NAIVE local string ("2026-08-28T14:15") plus a
    top-level "utc_offset_seconds" telling you what that local time means.

    Storing the naive string was fine in SQLite (TEXT is TEXT). It is not fine
    in PostgreSQL: posted_at is TIMESTAMPTZ NOT NULL, so Postgres would read a
    naive string in the *server's* timezone (UTC on Supabase) and silently
    shift every Open-Meteo row by 5.5 hours. No error, just wrong data - which
    is worse than an error, because nothing would tell us.

    We convert to UTC here rather than at insert time so the value is already
    unambiguous by the time it reaches cleaning.parse_timestamp(), the
    scheduler's age filter, and the ML teammate's CSV export.
    """
    raw = current.get("time")
    if not raw:
        return datetime.now(timezone.utc).isoformat()

    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()

    if dt.tzinfo is None:
        # Attach the offset Open-Meteo told us this local time was measured in.
        offset = block.get("utc_offset_seconds", 0) or 0
        dt = dt.replace(tzinfo=timezone(timedelta(seconds=offset)))

    return dt.astimezone(timezone.utc).isoformat()


def _fetch_batch_live(cities: list) -> dict:
    """
    One HTTP call for a batch of cities. Open-Meteo accepts comma-separated
    latitude/longitude lists and returns a JSON array in the same order.
    """
    import requests

    lats = ",".join(str(c[2]) for c in cities)
    lons = ",".join(str(c[3]) for c in cities)

    params = {
        "latitude": lats,
        "longitude": lons,
        "current": ",".join(OPENMETEO_CURRENT_VARS),
        "timezone": "Asia/Kolkata",
    }
    resp = requests.get(OPENMETEO_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    # Single-location requests return a dict; multi-location return a list.
    return payload if isinstance(payload, list) else [payload]


def _to_raw(city_name: str, state: str, lat: float, lon: float, block: dict) -> dict:
    current = block.get("current", {}) or {}
    units = block.get("current_units", {}) or {}

    category, summary = _classify(current)
    observed_at = _observed_at_utc(current, block)

    temp = current.get("temperature_2m")
    precip = current.get("precipitation")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    gusts = current.get("wind_gusts_10m")

    # Build a readable sentence so this row looks like every other row in the
    # table and the same text-based tooling (search, the dashboard, the ML
    # teammate's text pipeline) works on it unchanged.
    text = (
        f"Observed conditions in {city_name.title()}, {state}: {summary}. "
        f"Temperature {temp}{units.get('temperature_2m', ' C')}, "
        f"humidity {humidity}{units.get('relative_humidity_2m', '%')}, "
        f"precipitation {precip}{units.get('precipitation', ' mm')}, "
        f"wind {wind}{units.get('wind_speed_10m', ' km/h')} "
        f"(gusts {gusts}{units.get('wind_gusts_10m', ' km/h')})."
    )

    return {
        "source": SOURCE_NAME,
        # Stable per city per observation timestamp, so re-running inside the
        # same 15-minute model interval de-duplicates instead of piling up.
        "source_post_id": f"{city_name}-{observed_at}",
        "source_url": "https://open-meteo.com/",
        "author": "Open-Meteo (numerical weather model)",
        "text_raw": text,
        "posted_at": observed_at,
        "location_hint": f"{city_name.title()}, {state}",
        "media_urls": [],
        "media_type": "none",
        "language": "en",
        # Derived from measured values, so pass it explicitly rather than
        # letting the generic keyword matcher re-guess it from the sentence.
        "event_category": category,
        # Authoritative measured data, not a user claim - mark it verified so
        # the dashboard and the ML teammate can treat it as a trusted baseline.
        "verification_status": "verified",
        "extra": {
            "measured": current,
            "units": units,
            "derived_category": category,
            "derived_summary": summary,
            "latitude": lat,
            "longitude": lon,
        },
    }


def fetch(demo: bool = False) -> list:
    if demo:
        path = os.path.join(SAMPLE_DATA_DIR, "openmeteo_sample.json")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        return [
            _to_raw(i["city"], i["state"], i["latitude"], i["longitude"], i["block"])
            for i in items
        ]

    # (name, state, lat, lon) for every configured city
    cities = [(name, meta[0], meta[1], meta[2]) for name, meta in INDIAN_CITIES.items()]

    # De-duplicate coordinates - several aliases share a location
    # (bengaluru/bangalore, vizag/visakhapatnam, kochi/cochin...). Sending the
    # same lat/lon twice just wastes quota and creates redundant rows.
    seen_coords = set()
    unique_cities = []
    for c in cities:
        key = (round(c[2], 4), round(c[3], 4))
        if key in seen_coords:
            continue
        seen_coords.add(key)
        unique_cities.append(c)

    results = []
    for i in range(0, len(unique_cities), OPENMETEO_BATCH_SIZE):
        batch = unique_cities[i:i + OPENMETEO_BATCH_SIZE]
        try:
            blocks = _fetch_batch_live(batch)
        except Exception as exc:
            print(f"[openmeteo] batch {i // OPENMETEO_BATCH_SIZE + 1} failed: {exc}")
            continue

        for city, block in zip(batch, blocks):
            try:
                results.append(_to_raw(city[0], city[1], city[2], city[3], block))
            except Exception as exc:
                print(f"[openmeteo] failed to parse {city[0]}: {exc}")

    return results
