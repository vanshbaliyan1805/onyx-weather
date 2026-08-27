"""
generate_synthetic.py
---------------------
Generates labelled FABRICATED weather reports for training a fake-report
detector, and writes them into the database with ml_label = 1.

    python generate_synthetic.py --count 4000 --db weather_reports.db

WHY THIS EXISTS
  Misinformation in the wild is not labelled as misinformation. You cannot
  collect positive examples for a supervised fake-detector - they have to be
  synthesized. This is standard practice for rare-class problems (spam,
  fraud, abuse) and not a shortcut.

HOW THESE ROWS ARE MARKED
  source              'synthetic'   - never a real platform name
  ml_label             1            - the supervised target
  verification_status 'unverified'  - deliberately NOT 'fake', so the two
                                      columns stay independent and a model
                                      can't cheat off the status field
  raw_json             {"synthetic": true, "archetype": ..., ...}

  Every row is auditable and impossible to mistake for collected data.

THREE TIERS OF DIFFICULTY
  Real misinformation is not all shouty. A detector trained only on ALL-CAPS
  clickbait learns to detect capital letters, so the generator produces:

    sensational  ~35%  ALL CAPS, !!!, forward-me, conspiracy framing
    plausible    ~40%  reads like a genuine bulletin, but fabricated
    subtle       ~25%  mostly true-sounding, with inflated figures or
                       misattributed authority - the hard cases

  The subtle tier is what stops the classifier being trivial.
"""

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from config import INDIAN_CITIES
from cleaning import normalize_record
import db

SOURCE_NAME = "synthetic"

# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

HANDLES = [
    "weatherupdates_in", "india_alerts24", "mausam_news", "bharat_weather",
    "rain_watch_india", "disaster_alert_in", "citizen_reporter_9", "news_flash_bharat",
    "imd_updates_unofficial", "weather_warrior", "monsoon_tracker", "alert_india_now",
    "breaking_bharat", "desi_weather", "storm_watch_in", "climate_india_live",
]

SENSATIONAL_OPENERS = [
    "BREAKING:", "URGENT:", "ALERT!!!", "MUST READ:", "SHOCKING:",
    "*** URGENT ***", "BREAKING NEWS!!", "EMERGENCY ALERT:", "ATTENTION ALL:",
    "Forwarded as received:", "RED ALERT!!!", "MASSIVE UPDATE:",
]

CONSPIRACY = [
    "Government is hiding this from public.",
    "Media will not show you this.",
    "Officials refusing to confirm but sources say otherwise.",
    "This news is being suppressed everywhere.",
    "They deleted the original post, sharing again.",
    "Admin trying to remove this, forward fast.",
    "No news channel is covering this. Wonder why.",
    "IMD knows but not telling anyone.",
]

CALLS_TO_ACTION = [
    "Forward to all groups immediately.",
    "Share before it gets deleted!!",
    "Send to your family right now.",
    "Please circulate widely.",
    "Tag everyone you know.",
    "Copy paste and forward.",
    "Save this message and share.",
    "Don't ignore, forward to 10 people.",
]

HINGLISH_FRAGMENTS = [
    "Sab log dhyan do.",
    "Bahut serious situation hai.",
    "Ghar se mat niklo.",
    "Turant share karo.",
    "Koi bhi bahar na jaye.",
    "Poora sheher band ho gaya hai.",
    "Sarkar kuch nahi bata rahi.",
]

FAKE_AUTHORITIES = [
    "IMD Special Bulletin", "NDMA Emergency Cell", "Central Weather Command",
    "National Disaster Control Room", "IMD Regional Director",
    "Meteorological Emergency Division", "State Disaster Authority HQ",
    "IMD Chief Scientist", "National Weather Emergency Board",
]


# Link-shorteners and plausible-but-fake news domains. Real misinformation
# very often carries a link, and REAL collected data does too (26% of the RSS
# and Mastodon rows contain a URL).
#
# Without these, "contains http" becomes a perfect predictor of the genuine
# class and the classifier learns to detect hyperlinks instead of falsehood.
# No real news domain is used - these are invented.
FAKE_LINKS = [
    "https://bit.ly/{code}", "https://tinyurl.com/{code}",
    "https://newsflash-bharat.co/{code}", "https://weatheralert-india.info/{code}",
    "https://breaking-updates.net/{code}", "https://t.co/{code}",
    "https://indiaweather-live.org/{code}", "https://alerts-today.in/{code}",
]

# Trailing fragments that lengthen a post without changing its claim. Used to
# widen the synthetic length distribution, which would otherwise be far
# narrower than the real one (another giveaway).
LONG_TAILS = [
    " Local authorities have not issued any official statement so far, but "
    "residents in several neighbourhoods report that conditions have been "
    "deteriorating since early morning.",
    " Multiple eyewitnesses have described the situation as unprecedented, "
    "with several roads impassable and public transport suspended across the "
    "affected zones until further notice.",
    " Emergency services are reportedly stretched thin, and volunteers have "
    "begun coordinating relief efforts independently in the worst hit "
    "localities. More updates will follow as information becomes available.",
    " Schools, colleges and government offices are expected to remain shut, "
    "and residents have been urged to avoid all non-essential travel until "
    "the situation improves.",
]


def _rand_code(n=7):
    return "".join(random.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(n))


def _decorate(text: str) -> str:
    """
    Post-process a generated claim so the synthetic class matches the real
    class on surface features that have nothing to do with truthfulness.

    Two adjustments, both fixing measured leaks:
      - roughly a quarter get a URL (real rows: 26%)
      - length is spread wider (real median 246 chars vs synthetic 164)
    """
    # Lengthen some, shorten others.
    roll = random.random()
    if roll < 0.22:
        text = text + random.choice(LONG_TAILS)
        if random.random() < 0.35:
            text = text + random.choice(LONG_TAILS)
    elif roll < 0.38:
        # Clip to a short, punchy forward.
        sentences = [s for s in text.split(". ") if s]
        text = sentences[0].rstrip(".") + "."

    # Attach a link about a quarter of the time.
    if random.random() < 0.26:
        link = random.choice(FAKE_LINKS).format(code=_rand_code())
        text = f"{text} {link}"

    return text


def _pick_city():
    name, (state, lat, lon) = random.choice(list(INDIAN_CITIES.items()))
    return name.title(), state


# --------------------------------------------------------------------------
# Tier 1 — sensational. Obvious clickbait / panic forwards.
# --------------------------------------------------------------------------

def gen_sensational():
    city, state = _pick_city()
    kind = random.choice(["rain", "flood", "cyclone", "heat", "storm", "wind"])

    if kind == "rain":
        mm = random.randint(400, 1200)
        hrs = random.choice([1, 2, 3, 6])
        body = (f"{mm}mm rain expected in {city} in next {hrs} hours. "
                f"Worst rainfall in {random.randint(50, 200)} years.")
        cat = "rainfall"
    elif kind == "flood":
        body = (f"ENTIRE {city.upper()} UNDER WATER. Water level crossed "
                f"{random.randint(8, 25)} feet in most areas. "
                f"{random.randint(50, 900)} people missing.")
        cat = "flooding"
    elif kind == "cyclone":
        kmph = random.randint(200, 400)
        body = (f"Super Cyclone with {kmph}kmph winds will hit {city} "
                f"in {random.randint(6, 48)} hours. Total destruction expected.")
        cat = "cyclone"
    elif kind == "heat":
        t = random.randint(52, 64)
        body = (f"Temperature in {city} touched {t} degrees today. "
                f"{random.randint(20, 400)} deaths reported already.")
        cat = "heatwave"
    elif kind == "storm":
        body = (f"Massive thunderstorm hitting {city} right now. "
                f"Lightning killed {random.randint(10, 80)} people in one hour.")
        cat = "thunderstorm"
    else:
        kmph = random.randint(150, 300)
        body = (f"{kmph}kmph winds tearing through {city}. "
                f"Buildings collapsing, roofs flying off everywhere.")
        cat = "strong_wind"

    parts = [random.choice(SENSATIONAL_OPENERS), body]
    if random.random() < 0.6:
        parts.append(random.choice(CONSPIRACY))
    if random.random() < 0.25:
        parts.append(random.choice(HINGLISH_FRAGMENTS))
    if random.random() < 0.75:
        parts.append(random.choice(CALLS_TO_ACTION))

    text = " ".join(parts)
    if random.random() < 0.3:
        text = text.upper()
    if random.random() < 0.4:
        text = text.replace(".", random.choice(["!!", "!!!", "."]))

    return text, cat, city, state, "sensational"


# --------------------------------------------------------------------------
# Tier 2 — plausible. Reads like a genuine bulletin, but fabricated.
# --------------------------------------------------------------------------

def gen_plausible():
    city, state = _pick_city()
    authority = random.choice(FAKE_AUTHORITIES)
    kind = random.choice(["rain", "flood", "heat", "fog", "wind", "storm", "dust"])

    if kind == "rain":
        mm = random.randint(180, 420)
        body = (f"{authority} has issued a RED alert for {city}, {state}. "
                f"Extremely heavy rainfall of {mm}mm expected over the next "
                f"{random.choice([12, 24, 36, 48])} hours. All schools and "
                f"colleges ordered shut.")
        cat = "rainfall"
    elif kind == "flood":
        body = (f"{authority} confirms flood situation in {city} district. "
                f"{random.randint(12, 90)} villages submerged, "
                f"{random.randint(2000, 60000)} people evacuated overnight. "
                f"Army has been called in.")
        cat = "flooding"
    elif kind == "heat":
        t = random.randint(46, 51)
        body = (f"{authority} declares severe heatwave in {city}, {state}. "
                f"Maximum temperature recorded at {t}C, "
                f"{random.randint(4, 9)} degrees above normal. "
                f"Section 144 imposed between 11am and 4pm.")
        cat = "heatwave"
    elif kind == "fog":
        body = (f"{authority} advisory: dense fog reduces visibility in {city} "
                f"to under {random.randint(20, 90)} metres. "
                f"{random.randint(40, 220)} flights cancelled, "
                f"{random.randint(30, 150)} trains suspended indefinitely.")
        cat = "fog"
    elif kind == "wind":
        body = (f"{authority} warns of squall over {city}, {state} with wind "
                f"speeds reaching {random.randint(90, 140)}kmph. "
                f"Residents advised to remain indoors until further notice.")
        cat = "strong_wind"
    elif kind == "storm":
        body = (f"{authority} bulletin: severe thunderstorm with hail expected "
                f"over {city} and adjoining areas. Crop damage across "
                f"{random.randint(5000, 90000)} hectares anticipated.")
        cat = "thunderstorm"
    else:
        body = (f"{authority} issues dust storm warning for {city}, {state}. "
                f"Visibility expected to drop below {random.randint(100, 500)}m. "
                f"Air quality index projected to cross {random.randint(450, 900)}.")
        cat = "dust_storm"

    extras = [
        f" Control room number {random.randint(1000, 9999)} activated.",
        f" Helpline: 1800-{random.randint(100, 999)}-{random.randint(1000, 9999)}.",
        " All emergency services on standby.",
        " District administration on high alert.",
        "",
    ]
    text = body + random.choice(extras)
    return text, cat, city, state, "plausible"


# --------------------------------------------------------------------------
# Tier 3 — subtle. Mostly true-sounding; the hard cases.
# --------------------------------------------------------------------------

def gen_subtle():
    city, state = _pick_city()
    kind = random.choice(["figure", "attribution", "stale", "scope", "prediction"])

    if kind == "figure":
        mm = random.randint(95, 180)
        text = (f"Heavy rainfall continues in {city} with {mm}mm recorded since "
                f"morning. Waterlogging reported in low lying areas, traffic "
                f"movement affected on main routes.")
        cat = "rainfall"
    elif kind == "attribution":
        text = (f"As per IMD, {city} will receive continuous rainfall for the "
                f"next {random.randint(5, 12)} days without any break. "
                f"Residents should stock essentials.")
        cat = "rainfall"
    elif kind == "stale":
        text = (f"Visuals from {city} showing severe flooding across the city. "
                f"Situation worsening by the hour, several localities cut off "
                f"from the mainland.")
        cat = "flooding"
    elif kind == "scope":
        text = (f"Complete shutdown in {city}, {state} due to weather conditions. "
                f"All offices, markets and transport services suspended till "
                f"further orders.")
        cat = "other"
    else:
        text = (f"Weather models indicate a low pressure system will intensify "
                f"and make landfall near {city} by {random.choice(['Monday','Tuesday','Wednesday','the weekend'])}. "
                f"Coastal districts should prepare for evacuation.")
        cat = "cyclone"

    return text, cat, city, state, "subtle"


GENERATORS = (
    [gen_sensational] * 35 +
    [gen_plausible] * 40 +
    [gen_subtle] * 25
)


def build_records(count: int, days_back: int, seed: int) -> list:
    random.seed(seed)
    now = datetime.now(timezone.utc)
    records, seen_text = [], set()
    attempts = 0

    while len(records) < count and attempts < count * 20:
        attempts += 1
        text, category, city, state, tier = random.choice(GENERATORS)()
        text = _decorate(text)

        if text in seen_text:
            continue          # keep every row textually distinct
        seen_text.add(text)

        posted = now - timedelta(
            seconds=random.randint(0, days_back * 24 * 3600)
        )
        idx = len(records)

        records.append({
            "source": SOURCE_NAME,
            "source_post_id": f"syn-{seed}-{idx:05d}",
            "source_url": None,
            "author": random.choice(HANDLES),
            "text_raw": text,
            "posted_at": posted.isoformat(),
            "location_hint": f"{city}, {state}",
            "media_urls": [],
            "media_type": "none",
            "language": "en",
            "event_category": category,
            # Deliberately NOT 'fake' - keeps this column independent of the
            # training target so a model can't cheat off it.
            "verification_status": "unverified",
            "ml_label": 1,
            "extra": {
                "synthetic": True,
                "generator": "generate_synthetic.py",
                "archetype": tier,
                "seed": seed,
                "note": "FABRICATED for ML training. Not a real report.",
            },
        })

    return records


def main():
    ap = argparse.ArgumentParser(description="Generate labelled fake weather reports")
    ap.add_argument("--count", type=int, default=4000)
    ap.add_argument("--db", default=None, help="target database (default: config DB_PATH)")
    ap.add_argument("--days-back", type=int, default=8,
                    help="spread timestamps over this many days")
    ap.add_argument("--seed", type=int, default=20260826)
    ap.add_argument("--dry-run", action="store_true", help="print samples, write nothing")
    args = ap.parse_args()

    records = build_records(args.count, args.days_back, args.seed)
    print(f"Generated {len(records)} distinct fabricated records.")

    tiers = {}
    for r in records:
        t = r["extra"]["archetype"]
        tiers[t] = tiers.get(t, 0) + 1
    for t, n in sorted(tiers.items()):
        print(f"  {t:<12} {n:>5}  ({100*n/len(records):.0f}%)")

    if args.dry_run:
        print("\nSamples:\n")
        for tier in ("sensational", "plausible", "subtle"):
            ex = next(r for r in records if r["extra"]["archetype"] == tier)
            print(f"[{tier}]  {ex['text_raw'][:150]}\n")
        return

    target = args.db or db.DB_PATH
    db.init_db(target)

    counts = {}
    for raw in records:
        normalized = normalize_record(raw)
        result = db.insert_record(normalized, db_path=target)
        counts[result] = counts.get(result, 0) + 1

    print(f"\nWritten to {target}:")
    for k, v in sorted(counts.items()):
        print(f"  {k:<20} {v}")


if __name__ == "__main__":
    main()
