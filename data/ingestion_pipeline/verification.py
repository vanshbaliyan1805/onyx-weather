"""
verification.py
---------------
Checks what a post CLAIMS against what the weather actually DID.

This is not a model. It is a lookup and a comparison:

    1. what does the post assert?    flooding, Mumbai, 30 Aug 18:00
    2. what was measured there?      Open-Meteo: 0.4 mm over 24 hours
    3. do they agree?                no  ->  contradicted

Training a network to learn "0.4 mm is not a flood" would be strictly worse
than the comparison below - it would need labelled examples we do not have,
and it could not show its working. A rule can hand someone the API response.

Why it complements the classifier
---------------------------------
The fake-detection model reads the sentence and asks "does this sound
fabricated". It never checks anything, so a calm, plausible lie - "light rain
in Jaipur this evening" on a bone-dry day - walks straight past it.

This does the opposite: it has no opinion about how the post is written, only
about whether the world agrees with it. Between them they cover the loud lies
and the quiet ones.

Honest naming
-------------
Open-Meteo is a numerical weather model assimilating global observation
networks. It is not IMD. Describe results as "cross-referenced against
Open-Meteo observational data", never as "verified against official IMD
records" - the difference will matter if anyone knowledgeable asks.
"""

import re
from datetime import datetime, timedelta, timezone

# Sources whose posted_at is the time of the CLAIM. News feeds are excluded:
# an RSS item's timestamp is when the article was published, and the article
# is often about somewhere else and some time ago. Checking "Nepal floods"
# against the weather in the resolved Indian city at publication time marks
# accurate journalism as contradicted - which is worse than not checking it.
CHECKABLE_SOURCES = {"mastodon", "bluesky", "citizen"}

# Accounts that relay news headlines into a social feed. They arrive with
# source='mastodon', so the RSS exclusion above misses them entirely - and
# they have exactly the same problem: the timestamp is when the bot posted,
# not when the weather happened, and the story is often about somewhere else.
#
# @EarthInsider was being flagged 'contradicted' for "Delhi-NCR Issues Red
# Alert as Heavy Rain Paralyses City" because 0.0mm fell at the Delhi
# coordinate in the 24h before the bot posted. The article was real. Marking
# accurate journalism as fake is the worst failure this system can have, so
# these are ruled unverifiable rather than judged.
NEWS_RELAY_AUTHORS = {
    "earthinsider", "earthinsidernews", "weatherbot", "newsbot", "rssbot",
    "feedbot", "breakingnews", "disasternews", "quakebot",
}
RELAY_SUFFIXES = ("bot", "_news", "news", "feed", "rss")


# Regions, not cities. The failsafe list in config.py resolves these to a
# representative coordinate so a post about "Konkan" or "Delhi-NCR" is
# COLLECTED instead of dropped as no_location - but one point cannot stand in
# for a region hundreds of kilometres across, so they are never judged
# against it. Measuring Konkan at Ratnagiri and declaring a Sindhudurg
# cloudburst false is the Nepal-floods mistake with a shorter drive.
REGION_PLACES = {
    "konkan", "vidarbha", "marathwada", "ncr", "delhi ncr", "delhi-ncr",
    "malabar", "coastal andhra", "rayalaseema", "saurashtra", "kutch",
    "bundelkhand", "terai", "sundarbans", "north india", "south india",
    "east india", "west india", "central india", "northeast india",
    "western ghats", "eastern ghats", "gangetic plains", "himalayas",
}


def looks_like_relay(author) -> bool:
    """True for automated news-relay accounts. Handle only, never content."""
    if not author:
        return False
    # Strip the instance: @EarthInsider@mastodon.social -> earthinsider
    a = author.strip().lower().lstrip("@").split("@")[0]
    if a in NEWS_RELAY_AUTHORS:
        return True
    return any(a.endswith(s) for s in RELAY_SUFFIXES)

# Thresholds over a 24-hour window ending at the post's timestamp.
#   below `denies`  -> the measurement contradicts the claim
#   above `confirms`-> the measurement supports it
#   in between      -> unverifiable, deliberately
#
# The gap is the most important part. A post saying "heavy rain" when 4 mm
# fell is neither a lie nor a confirmation, and forcing it into a verdict
# would make the flag untrustworthy - which is the only thing it has.
RULES = {
    "flooding":     {"field": "precip", "denies": 1.0,  "confirms": 20.0, "unit": "mm"},
    # 0.2 rather than 0.5: "light showers, roads damp" in Leh was called
    # contradicted on a day that recorded 0.4mm, which is precisely what
    # light showers look like. Only a genuinely dry day should deny a
    # rainfall claim.
    "rainfall":     {"field": "precip", "denies": 0.2,  "confirms": 5.0,  "unit": "mm"},
    "heatwave":     {"field": "temp",   "denies": 32.0, "confirms": 38.0, "unit": "C"},
    "strong_wind":  {"field": "wind",   "denies": 12.0, "confirms": 28.0, "unit": "km/h"},
    "thunderstorm": {"field": "precip", "denies": 0.2,  "confirms": 3.0,  "unit": "mm"},
}

WINDOW_HOURS = 24
BATCH = 40

AGREES = "agrees"
CONTRADICTED = "contradicted"
UNVERIFIABLE = "unverifiable"

# The single column everything else collapses into. Four values, not two:
# a hard fake/real split would have to put 0.51 and 0.998 in the same bucket,
# and would have to guess about rows nothing has looked at yet.
#
#   fake       both signals agree, or the model is overwhelmingly sure
#   suspect    exactly one signal fired - worth a human glance
#   ok         nothing fired
#   unchecked  no model score and no measurement check yet
#
# Written as one SQL statement so it works unchanged on SQLite and Postgres,
# and so it can be recomputed from scratch at any time - the verdict is
# derived, never authored, which means it can never drift from the evidence.
# Order matters. Every clause that FIRES is tested before the clause that
# admits ignorance, so a confident model score still lands as 'fake' even if
# the cross-reference has not run yet. Only when nothing fired does the
# missing-evidence test get a say - and then a row that is half-checked
# reports 'unchecked' rather than quietly passing as 'ok'.
#
# 'ok' now means what it says: both signals ran, and both were quiet.
VERDICT_SQL = """
UPDATE weather_reports SET verdict = CASE
    WHEN fake_probability >= 0.5 AND measurement_check = 'contradicted'
        THEN 'fake'
    WHEN fake_probability >= 0.9
        THEN 'fake'
    WHEN measurement_check = 'contradicted'
        THEN 'suspect'
    WHEN fake_probability >= 0.5
        THEN 'suspect'
    WHEN fake_probability IS NULL OR measurement_check IS NULL
        THEN 'unchecked'
    ELSE 'ok'
END
"""


def _hybrid_owns_verdict(db_module) -> bool:
    """True once the hybrid layer is installed on this database."""
    try:
        with db_module.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT hybrid_score FROM weather_reports LIMIT 1")
                cur.fetchall()
        return True
    except Exception:
        return False


def recompute_verdicts(db_module):
    """
    Refresh the `verdict` column for every row from the current evidence.

    Steps aside when the hybrid layer is present. Two writers with different
    rules produced a column whose meaning depended on which worker ran last:
    this SQL requires BOTH signals before a row may be 'ok', the hybrid
    blend requires only one, so 373 rows flipped from 'unchecked' to 'ok'
    with no new evidence. One owner, one definition.
    """
    if _hybrid_owns_verdict(db_module):
        print("  verdict column: owned by hybrid_worker.py, not recomputed")
        return {}

    with db_module.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(VERDICT_SQL)
    with db_module.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT verdict, COUNT(*) FROM weather_reports "
                        "GROUP BY verdict ORDER BY 2 DESC")
            return dict(cur.fetchall())

# Numbers a post asserts about the weather, with their units. Checking the
# CATEGORY alone is too blunt: "340mm cloudburst" in a city that got 2.9mm is
# a 117x exaggeration, but a category check only asks "did it rain at all?"
# and shrugs. The number is right there in the text - compare it directly.
# The leading minus is captured on purpose. Without it "-15°C" was read as
# "15°C" - the sign silently dropped - and a physically impossible claim
# became a mild one. The lookbehind still rejects the minus inside a range
# like "30-40mm", because there the character before it is a digit; the
# regex then matches "40mm" on its own, which is what was meant.
CLAIM_RE = re.compile(
    r"(?<![\w.])(-?\d{1,4}(?:\.\d+)?)\s*"
    r"(mm|cm|km ?/ ?h|kmph|km/h|°\s?c|degrees?\s*(?:celsius)?|c\b)",
    re.IGNORECASE,
)

# How far past the measurement a claim has to be before it counts as
# contradicted. Deliberately generous - a post saying 30mm when 22mm fell is
# rounding, not lying, and a flag nobody trusts is worse than no flag.
RAIN_RATIO = 8.0        # claimed at least 8x the measured total, AND
RAIN_ABSOLUTE = 25.0    # at least 25mm more than actually fell
TEMP_MARGIN = 8.0       # degrees clear of the day's peak OR its low
WIND_RATIO = 3.0
WIND_ABSOLUTE = 60.0

# Snow needs air near freezing. Generous by design: 5C leaves room for hill
# stations and for the gap between a 2m air reading and ground conditions.
SNOW_MAX_TEMP = 5.0

# A nominal "ordinary" temperature, used only to decide which of several
# figures in a post is the most extreme one. 25C is unremarkable anywhere in
# India, so both 45 and -15 read as far from it.
TEMP_NEUTRAL = 25.0


def extract_claim(text: str):
    """
    Pull the largest weather magnitude a post asserts.

    Returns (value, kind) where kind is 'rain' | 'temp' | 'wind', or None.
    Percentages are ignored - "23% shortfall" is a statistic about a season,
    not a claim about what fell today.
    """
    if not text:
        return None
    best = None
    for m in CLAIM_RE.finditer(text):
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        unit = m.group(2).lower().replace(" ", "")
        if unit == "cm":
            value, kind = value * 10.0, "rain"
        elif unit == "mm":
            kind = "rain"
        elif unit in ("km/h", "kmph", "km/h"):
            kind = "wind"
        else:
            kind = "temp"
            # Wide enough to admit a claimed cold snap. The old floor of 15
            # threw away exactly the figures worth checking.
            if not (-40 <= value <= 80):
                continue
        if value < 0 and kind in ("rain", "wind"):
            continue                        # negative rainfall is a typo
        if best is None or _extremity(value, kind) > _extremity(*best):
            best = (value, kind)
    return best


def _extremity(value, kind):
    """
    How far from ordinary a claimed figure is, used only to pick the single
    most extreme number in a post. Rain and wind are extreme when large;
    temperature is extreme in BOTH directions, which is why it cannot just
    be sorted by magnitude - "-15C" has to outrank "31C".
    """
    if kind == "temp":
        return abs(value - TEMP_NEUTRAL)
    return value


def _magnitude_verdict(claimed, kind, m):
    """
    Compare an asserted number against the measurement. Returns (verdict, note)
    or None when the claim is not far enough out to be worth calling.
    """
    if kind == "rain":
        actual = m["precip"]
        if actual is None:
            return None
        if claimed >= max(actual * RAIN_RATIO, actual + RAIN_ABSOLUTE):
            factor = f"{claimed / actual:.0f}x" if actual > 0.05 else "none at all"
            return CONTRADICTED, (f"claims {claimed:g}mm - only {actual:g}mm "
                                  f"recorded in 24h ({factor})")
    elif kind == "temp":
        actual = m["temp"]
        if actual is None:
            return None
        if claimed >= actual + TEMP_MARGIN:
            return CONTRADICTED, (f"claims {claimed:g}C - peak was "
                                  f"{actual:g}C in 24h")
        # The cold direction. Every comparison in this module used to ask
        # only "is the claim too high", so "-15C in Mumbai" sailed through:
        # it is not hotter than the peak, therefore nothing to report. A
        # claim far BELOW the coldest hour is exactly as false.
        low = m.get("temp_min")
        if low is not None and claimed <= low - TEMP_MARGIN:
            return CONTRADICTED, (f"claims {claimed:g}C - lowest was "
                                  f"{low:g}C in 24h")
    elif kind == "wind":
        actual = m["wind"]
        if actual is None:
            return None
        if claimed >= max(actual * WIND_RATIO, actual + WIND_ABSOLUTE):
            return CONTRADICTED, (f"claims {claimed:g}km/h - peak was "
                                  f"{actual:g}km/h in 24h")
    return None

def fetch_history(coords: list, days: int = 7) -> dict:
    """
    Hourly history for a batch of coordinates.

    `past_days` on the forecast endpoint covers recent observed/analysed
    hours - exactly the window our 168-hour age filter allows. The archive
    endpoint is not used because it lags several days behind live data.

    Returns {(lat, lon): {datetime_utc: {precip, temp, wind, code}}}
    """
    import requests

    out = {}
    for i in range(0, len(coords), BATCH):
        chunk = coords[i:i + BATCH]
        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": ",".join(str(c[0]) for c in chunk),
                    "longitude": ",".join(str(c[1]) for c in chunk),
                    "hourly": "precipitation,temperature_2m,wind_speed_10m,weather_code",
                    "past_days": days,
                    "forecast_days": 1,
                    "timezone": "UTC",
                },
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"  ! history batch {i // BATCH + 1} failed: {exc}")
            continue

        blocks = payload if isinstance(payload, list) else [payload]
        for coord, block in zip(chunk, blocks):
            hourly = block.get("hourly") or {}
            times = hourly.get("time") or []
            series = {}
            for j, t in enumerate(times):
                try:
                    ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    continue
                series[ts] = {
                    "precip": hourly.get("precipitation", [None] * len(times))[j],
                    "temp":   hourly.get("temperature_2m", [None] * len(times))[j],
                    "wind":   hourly.get("wind_speed_10m", [None] * len(times))[j],
                    "code":   hourly.get("weather_code", [None] * len(times))[j],
                }
            if series:
                out[coord] = series
        print(f"  batch {i // BATCH + 1}: {len(chunk)} locations")
    return out


def _measure(series: dict, when: datetime):
    """Totals and peaks over the 24 hours leading up to `when`."""
    lo = when - timedelta(hours=WINDOW_HOURS)
    readings = [v for ts, v in series.items() if lo <= ts <= when]
    if not readings:
        return None

    temps = [r["temp"] for r in readings if r["temp"] is not None]
    winds = [r["wind"] for r in readings if r["wind"] is not None]
    return {
        # Rain accumulates, so it is summed. Temperature and wind are peaks -
        # a heatwave claim is about the day's maximum, not its average.
        "precip": round(sum((r["precip"] or 0.0) for r in readings), 2),
        "temp":     max(temps) if temps else None,
        "temp_min": min(temps) if temps else None,
        "wind":     max(winds) if winds else None,
        "codes":  [r["code"] for r in readings if r["code"] is not None],
    }


def check_claim(category: str, series: dict, when: datetime, source: str = None,
                text: str = None, author: str = None, city: str = None):
    """
    Returns (verdict, note).

    Two passes, in order:

      1. If the post states a NUMBER, compare that number against the
         measurement. This is the sharp check - "claims 340mm, 2.9mm fell"
         is specific, damning and anyone can verify it.
      2. Otherwise fall back to comparing the CATEGORY against thresholds,
         which is blunter but works on posts with no figures in them.

    verdict  'agrees' | 'contradicted' | 'unverifiable'
    """
    if source is not None and source not in CHECKABLE_SOURCES:
        return UNVERIFIABLE, "news source - publication time is not event time"
    if looks_like_relay(author):
        return UNVERIFIABLE, (f"@{author} is a news relay - post time is not "
                              f"event time")
    if city and city.strip().lower() in REGION_PLACES:
        return UNVERIFIABLE, (f"'{city}' is a region, too coarse to check "
                              f"against a single measurement point")
    if not series or not when:
        return UNVERIFIABLE, "no measurements for this location"

    m = _measure(series, when)
    if m is None:
        return UNVERIFIABLE, "no readings in the 24h before this post"

    # Pass 1 - the number the post actually states, if it states one. This
    # runs before the category lookup so a wild figure is caught even in a
    # post whose category we could not classify.
    claim = extract_claim(text)
    if claim:
        hit = _magnitude_verdict(claim[0], claim[1], m)
        if hit:
            return hit

    # Snow is not a threshold question, it is a physics question, so it is
    # handled before the threshold table. A post can claim snow with no
    # figures at all - "heavy snowfall in Mumbai tonight" - and the number
    # check above has nothing to bite on.
    if category == "snow":
        low = m.get("temp_min")
        if low is None:
            return UNVERIFIABLE, "claims snowfall - no temperature readings"
        if low > SNOW_MAX_TEMP:
            return CONTRADICTED, (f"claims snowfall - lowest temperature was "
                                  f"{low:g}C in 24h, never close to freezing")
        return UNVERIFIABLE, f"claims snowfall - lowest was {low:g}C"

    # Pass 2 - category thresholds.
    rule = RULES.get(category)
    if rule is None:
        return UNVERIFIABLE, f"'{category}' makes no measurable claim"

    value = m[rule["field"]]
    if value is None:
        return UNVERIFIABLE, "measurement unavailable"

    unit = rule["unit"]
    window = " in 24h" if rule["field"] == "precip" else " (24h peak)"
    shown = f"{value}{unit}{window}"

    # Thunderstorms are visible in the WMO code directly (95/96/99), which is
    # better evidence than rainfall alone.
    if category == "thunderstorm" and any(cd in (95, 96, 99) for cd in m["codes"]):
        return AGREES, f"claims thunderstorm - storm recorded, {shown}"

    if value < rule["denies"]:
        return CONTRADICTED, f"claims {category} - only {shown} recorded"
    if value >= rule["confirms"]:
        return AGREES, f"claims {category} - {shown} recorded"
    return UNVERIFIABLE, f"claims {category} - {shown}, too close to call"
