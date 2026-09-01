"""
rules.py
--------
Two signals the classifier and the measurement check both miss.

1. PHYSICAL IMPOSSIBILITY - claims that are wrong everywhere, always.
   "310 kmph winds" is false in Visakhapatnam in October and equally false
   in every other place and month, because the planet does not do that. This
   needs no API, no location and no model; it is a comparison against
   recorded extremes.

   It matters because it is the one check that still works when everything
   else fails: no Open-Meteo coverage, no resolved city, no timestamp in the
   window, model not run yet. A post can be caught on the text alone.

2. SOURCE CREDIBILITY - who is saying it.
   Scored deliberately weakly. An unknown handle is not evidence of lying,
   it is the normal state of a citizen report, so `UNKNOWN_RISK` sits at
   0.5 (neutral) and the blend gives this signal the smallest weight. It
   exists to break ties, never to decide on its own.

Deliberately NOT included: a sensationalism keyword score. VayuDrishti has
one, but our DistilBERT already reads exactly that - capitalisation, urgency,
severity language - so a keyword layer on top would count the same evidence
twice and make a shouty-but-true post look worse than the evidence supports.
"""

import re

# ---------------------------------------------------------------------------
# Recorded extremes, with the headroom a real system needs. Each pair is
# (implausible_above, certainly_impossible_above). Between the two the score
# ramps; past the second it is flat at the ceiling.
#
# Sources for the anchors: highest surface wind gust ever recorded is 408
# km/h (Barrow Island, 1996); India's highest reliable temperature is 51.0C
# (Phalodi, 2016); the world 24-hour rainfall record is about 1,825mm
# (Reunion) and India's is about 1,563mm (Cherrapunji).
# ---------------------------------------------------------------------------
LIMITS = {
    "wind": (260.0, 410.0),     # strongest Indian cyclone gusts sit near 260
    "temp": (51.0, 58.0),
    "temp_low": (-45.0, -60.0),  # Dras, one of the coldest inhabited places
    "rain": (1000.0, 1825.0),   # millimetres in a day
}

# Matches every magnitude in the text, not just the largest, because a post
# can bury one impossible figure among plausible ones.
CLAIM_RE = re.compile(
    r"(?<![\w.])(-?\d{1,5}(?:\.\d+)?)\s*"
    r"(mm|cm|km ?/ ?h|kmph|km/h|°\s?c|degrees?\s*(?:celsius)?|c\b)",
    re.IGNORECASE,
)


def _ramp(value, soft, hard):
    """0 below `soft`, 1 at or past `hard`, linear between."""
    if value < soft:
        return 0.0
    if value >= hard:
        return 1.0
    return (value - soft) / (hard - soft)


def extract_all(text):
    """Every (value, kind) the post asserts. kind is rain | temp | wind."""
    out = []
    if not text:
        return out
    for m in CLAIM_RE.finditer(text):
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        unit = m.group(2).lower().replace(" ", "")
        if unit == "cm":
            out.append((value * 10.0, "rain"))
        elif unit == "mm":
            out.append((value, "rain"))
        elif unit in ("km/h", "kmph"):
            out.append((value, "wind"))
        else:
            out.append((value, "temp"))
    return out


def physical_implausibility(text):
    """
    Returns (score 0-1, note). Independent of place and season.

    Only the worst claim counts. Averaging would let a post dilute one
    impossible number by surrounding it with reasonable ones, which is
    exactly what a careful fabricator would do.
    """
    worst, note = 0.0, None
    for value, kind in extract_all(text):
        if kind == "wind":
            if value < 0:
                continue
            s = _ramp(value, *LIMITS["wind"])
            msg = _phrase(s, f"claims {value:g} km/h winds",
                          "the strongest Indian cyclone gusts reach ~260 km/h",
                          "the strongest gust ever recorded on earth is "
                          "408 km/h")
        elif kind == "rain":
            if value < 0:
                continue
            s = _ramp(value, *LIMITS["rain"])
            msg = _phrase(s, f"claims {value:g}mm in a day",
                          "only a handful of days in Indian history exceed "
                          "1000mm",
                          "the world 24h record is about 1825mm")
        else:
            if value >= 0:
                s = _ramp(value, *LIMITS["temp"])
                msg = _phrase(s, f"claims {value:g}C",
                              "India's highest reliable reading is 51C",
                              "no reliable surface reading anywhere has "
                              "reached 58C")
            else:
                s = _ramp(-value, -LIMITS["temp_low"][0],
                          -LIMITS["temp_low"][1])
                msg = _phrase(s, f"claims {value:g}C",
                              "the coldest inhabited place in India sits "
                              "near -45C",
                              "no Indian station has approached -60C")
        if s > worst:
            worst, note = s, msg
    return worst, note


def _phrase(score, claim, soft_reason, hard_reason):
    """
    Word the finding honestly for where it sits on the ramp.

    A claim of 310 km/h and a claim of 900 km/h both score above zero, but
    only one of them is impossible. Saying "the record is 408" about a 310
    claim reads as a rebuttal that disproves itself, so the two bands get
    different sentences.
    """
    if score >= 1.0:
        return f"{claim} - physically impossible, {hard_reason}"
    if score >= 0.5:
        return f"{claim} - beyond anything recorded, {hard_reason}"
    return f"{claim} - implausibly high, {soft_reason}"


# ---------------------------------------------------------------------------
# Source credibility
# ---------------------------------------------------------------------------
# Substrings, matched case-insensitively against the author handle. Kept
# short and specific: "imd" as a substring would match "imdb" and half the
# Hindi words transliterated with those letters, so the entries are anchored
# with separators where it matters.
OFFICIAL = ("imd_", "imd.", "indiametdept", "mausam", "ndrf", "ndma",
            "cwc_india", "iitm", "moes", "sdma", "cyclone_warning",
            "rmc_", "meteo")
ESTABLISHED = ("skymet", "weatherchannel", "accuweather", "ndtv", "thehindu",
               "indianexpress", "timesofindia", "hindustantimes", "pti_news",
               "ani", "news18", "scroll_in", "thewire")

OFFICIAL_RISK = 0.05
ESTABLISHED_RISK = 0.25
UNKNOWN_RISK = 0.50        # deliberately neutral - most citizens are unknown
THROWAWAY_RISK = 0.75

# Handles that look machine-generated: a name followed by a long digit run,
# which is what the default suggestion looks like on every platform when the
# real name is taken. Weak evidence, hence the modest score.
THROWAWAY_RE = re.compile(r"\d{6,}$")


def source_risk(author, source=None):
    """Returns (score 0-1, note). Never decisive on its own."""
    if source == "openmeteo":
        return 0.0, "measurement feed, not a claim"
    if not author:
        return UNKNOWN_RISK, "no author recorded"
    a = author.strip().lower().lstrip("@")
    for frag in OFFICIAL:
        if frag in a:
            return OFFICIAL_RISK, f"@{author} matches an official handle"
    for frag in ESTABLISHED:
        if frag in a:
            return ESTABLISHED_RISK, f"@{author} is an established outlet"
    if THROWAWAY_RE.search(a):
        return THROWAWAY_RISK, f"@{author} looks like a throwaway handle"
    return UNKNOWN_RISK, f"@{author} is unrecognised"
