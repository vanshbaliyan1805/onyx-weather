"""
apply_failsafes.py
------------------
Widens what the pipeline can catch, without touching anything it already does.

    python failsafes\\apply_failsafes.py
    python failsafes\\apply_failsafes.py --revert

Run it from the ingestion_pipeline folder. It APPENDS a block to config.py
and one to cleaning.py, after backing both up to *.bak. It never rewrites an
existing line, so nothing you have already tuned can be clobbered, and it is
safe to run twice - the second run detects its own marker and stops.

What it adds and why
--------------------
1. HASHTAGS. `#weather` - the single most obvious weather hashtag on the
   internet - was not in the list, so three of seven test posts were never
   fetched. The list was written from Indian monsoon vocabulary and quietly
   assumed every report would use it. Now covers the generic tags, the cold
   half of the year (snow, coldwave), Hinglish (mausam, barish, andhi,
   toofan), city-specific tags, and alert levels.

2. REGIONS. A post about "Konkan" or "Delhi-NCR" resolved to no city and was
   dropped as no_location. These now resolve to a representative point so the
   post is COLLECTED - and verification.py refuses to judge them, because one
   coordinate cannot speak for a region. Collect, don't pretend to verify.

3. AMBIGUOUS PLACES. Salt Lake City's flood alerts were being filed in West
   Bengal. The same trap is set by every US town named after a British or
   Indian one - Salem, Kingston, Richmond, Oxford. These now need
   corroboration before a location is accepted.

4. SNOW CATEGORY. There was no snow keyword anywhere, so "snowfall in
   Chennai" classified as 'other' and no rule could reach it.
"""

import argparse
import os
import shutil
import sys

MARKER = "# === onyx failsafes: appended by apply_failsafes.py ==="

CONFIG_BLOCK = MARKER + '''
# Everything below EXTENDS what is already defined above. Nothing is replaced.
_g = globals()

# --- 1. hashtags -----------------------------------------------------------
_EXTRA_TAGS = [
    # the generic ones that were missing entirely
    "weather", "weatherupdate", "weathernews", "weatherforecast",
    "weatherwarning", "extremeweather", "IMDAlert", "IMDWarning",
    # the cold half of the year - the list was monsoon-only
    "snow", "snowfall", "snowstorm", "blizzard", "coldwave", "coldwaves",
    "frost", "temperature", "mausam",
    # Hinglish, which is how a lot of India actually posts about weather
    "barish", "baarish", "andhi", "toofan", "baadh", "garmi", "sardi",
    # storms and consequences
    "storm", "rainstorm", "cloudburst", "landslide", "waterlogged",
    "flashflood", "stormsurge", "gustywinds", "lightning",
    # alert levels
    "redalert", "orangealert", "yellowalert", "rainalert", "floodalert",
    "cycloneupdate", "heatalert",
    # city tags people actually use
    "chennairains", "bengalururains", "hyderabadrains", "punerains",
    "kolkatarains", "keralarains", "assamfloods", "biharfloods",
    "delhiweather", "mumbaiweather", "chennaiweather",
]
if "WEATHER_HASHTAGS" in _g:
    for _t in _EXTRA_TAGS:
        if _t not in WEATHER_HASHTAGS:
            WEATHER_HASHTAGS.append(_t)
# WEATHER_KEYWORDS was derived from the list at definition time, so extending
# the tags above does not reach it. Rebuild it here.
if "WEATHER_KEYWORDS" in _g:
    for _t in _EXTRA_TAGS:
        _k = _t.lower()
        if _k not in WEATHER_KEYWORDS:
            WEATHER_KEYWORDS.append(_k)

# --- 2. regions ------------------------------------------------------------
# Representative coordinates only. verification.py refuses to measurement-check
# anything in this list, so these exist purely so the post is collected and
# shows on the dashboard instead of being dropped as no_location.
_REGIONS = {
    "konkan":          ("Maharashtra",     16.9902, 73.3120),
    "vidarbha":        ("Maharashtra",     21.1458, 79.0882),
    "marathwada":      ("Maharashtra",     19.8762, 75.3433),
    "ncr":             ("Delhi",           28.6139, 77.2090),
    "delhi ncr":       ("Delhi",           28.6139, 77.2090),
    "delhi-ncr":       ("Delhi",           28.6139, 77.2090),
    "malabar":         ("Kerala",          11.2588, 75.7804),
    "coastal andhra":  ("Andhra Pradesh",  17.6868, 83.2185),
    "rayalaseema":     ("Andhra Pradesh",  15.8281, 78.0373),
    "saurashtra":      ("Gujarat",         22.3039, 70.8022),
    "kutch":           ("Gujarat",         23.2420, 69.6669),
    "bundelkhand":     ("Uttar Pradesh",   25.4484, 78.5685),
    "terai":           ("Uttar Pradesh",   26.7606, 83.3732),
    "sundarbans":      ("West Bengal",     21.9497, 88.9000),
    "western ghats":   ("Maharashtra",     18.7000, 73.4000),
    "gangetic plains": ("Uttar Pradesh",   25.3176, 82.9739),
}
if "INDIAN_CITIES" in _g:
    for _name, _meta in _REGIONS.items():
        INDIAN_CITIES.setdefault(_name, _meta)

# --- 4. snow category ------------------------------------------------------
# Inserted at the front so it is tested before "rainfall" - a snow post that
# also says "rain" should classify as snow.
if "EVENT_CATEGORY_KEYWORDS" in _g:
    if not any(_c == "snow" for _c, _ in EVENT_CATEGORY_KEYWORDS):
        EVENT_CATEGORY_KEYWORDS.insert(0, (
            "snow",
            ["snowfall", "snow", "snowstorm", "blizzard", "sleet",
             "snowing", "snow-covered"],
        ))
if "DEFAULT_EVENT_CATEGORY" not in _g:
    DEFAULT_EVENT_CATEGORY = "other"
'''

CLEANING_BLOCK = MARKER + '''
# Place names shared with somewhere else in the world. Being in this set does
# not block a name - it means the name alone is not enough, and something else
# in the post has to corroborate that we are in India.
#
# Salt Lake was the one that bit: eight National Weather Service flash-flood
# alerts from Salt Lake City, Utah were filed under Salt Lake, West Bengal and
# then measurement-checked against Kolkata. Every entry below is a place where
# the same thing can happen.
_EXTRA_AMBIGUOUS = {
    "salt lake", "salem", "kingston", "victoria", "richmond", "oxford",
    "cambridge", "springfield", "aurora", "columbia", "jackson", "franklin",
    "georgetown", "wellington", "hamilton", "london", "birmingham", "perth",
    "newcastle", "windsor", "kent", "surrey", "york", "dover", "bristol",
    "gloucester", "lincoln", "warren", "clinton", "madison", "monroe",
    "arlington", "burlington", "chester", "durham", "essex", "exeter",
    "greenwich", "hastings", "ipswich", "norwich", "preston", "reading",
    "rochester", "somerset", "stratford", "sunderland", "sussex", "wexford",
}
try:
    AMBIGUOUS_PLACES.update(_EXTRA_AMBIGUOUS)
except NameError:
    AMBIGUOUS_PLACES = set(_EXTRA_AMBIGUOUS)
except AttributeError:
    # Defined as a list or tuple rather than a set.
    AMBIGUOUS_PLACES = set(AMBIGUOUS_PLACES) | _EXTRA_AMBIGUOUS
'''

TARGETS = [("config.py", CONFIG_BLOCK), ("cleaning.py", CLEANING_BLOCK)]


def applied(path) -> bool:
    with open(path, encoding="utf-8") as f:
        return MARKER in f.read()


def apply():
    for name, block in TARGETS:
        if not os.path.exists(name):
            sys.exit(f"{name} not found - run this from ingestion_pipeline")
        if applied(name):
            print(f"  {name}: already patched, skipping")
            continue
        shutil.copy2(name, name + ".bak")
        with open(name, "a", encoding="utf-8") as f:
            f.write("\n\n" + block)
        print(f"  {name}: patched (backup at {name}.bak)")

    print("\nchecking it still imports...")
    sys.path.insert(0, os.getcwd())
    import config                                  # noqa: E402
    import cleaning                                # noqa: E402
    print(f"  hashtags:  {len(config.WEATHER_HASHTAGS)} tracked")
    print(f"  keywords:  {len(config.WEATHER_KEYWORDS)}")
    print(f"  places:    {len(config.INDIAN_CITIES)} resolvable")
    print(f"  ambiguous: {len(cleaning.AMBIGUOUS_PLACES)}")
    cats = [c for c, _ in config.EVENT_CATEGORY_KEYWORDS]
    print(f"  categories: {', '.join(cats)}")
    print("\nsanity check on the classifier:")
    for t in ["Light snowfall in Chennai this morning",
              "Heavy rain lashing Konkan since morning",
              "Dense fog across Delhi-NCR this morning"]:
        print(f"  {config and cleaning.guess_event_category(t):<14} {t}")
    print("\nnow run:")
    print("  python main.py fetch --source mastodon")


def revert():
    for name, _ in TARGETS:
        bak = name + ".bak"
        if os.path.exists(bak):
            shutil.copy2(bak, name)
            print(f"  {name}: restored from {bak}")
        else:
            print(f"  {name}: no backup found")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    revert() if a.revert else apply()
