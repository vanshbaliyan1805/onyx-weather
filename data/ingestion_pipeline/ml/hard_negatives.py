"""
hard_negatives.py
-----------------
Builds fake examples by CORRUPTING real posts, instead of writing new ones
from templates.

Why the template generator failed
---------------------------------
Measured on 640 rows: TF-IDF + logistic regression scored 0.994, DistilBERT
1.000. Neither model learned anything about misinformation. The top features
were `control room`, `emergency`, `alert` on one side and `delhi`, `nepal`,
`the`, `of` on the other - the generator's own phrase inventory against
ordinary news vocabulary.

The cause is structural, not a bug. Class 0 was written by hundreds of
different humans; class 1 came from about twenty templates. Two different
generative processes are trivially separable, so the classifier never has to
look at the claim.

The fix
-------
Take a REAL post and change only what it asserts:

    real  "IMD forecasts heavy rain across Kerala over the next two days"
    fake  "IMD forecasts unprecedented rain across Kerala within the hour"

    real  "Temperature crossed 41C in Nagpur today"
    fake  "Temperature crossed 67C in Nagpur today"

Same author, same register, same vocabulary, same structure. Usually 90%+ of
the tokens are identical. A model cannot separate these on style, because
there is no style difference - only the plausibility of the claim.

Expect accuracy to fall to somewhere around 0.70-0.85. That is the point.
0.994 was measuring the generator; 0.78 measures the task.

Each corrupted post keeps its source's dedup_hash, so the pair lands in the
same train/test fold and the model can never see one half of a pair while
being tested on the other.
"""

import random
import re

# Weather words swapped for implausibly extreme ones. Both sides are drawn
# from real Indian weather reporting, so no vocabulary is unique to one class.
SEVERITY = [
    # Each pattern absorbs any leading intensity word, so the replacement is a
    # complete noun phrase and nothing is left stranded in front of it. Without
    # that, "heavy waterlogging" became "Heavy complete submersion".
    (r"\b(?:heavy |light |moderate |isolated |scattered )?rain(?:fall|s)?\b",
        ["a 400mm cloudburst", "record-breaking torrential rain", "an unprecedented deluge"]),
    (r"\b(?:heavy |light |isolated |scattered )?showers?\b",
        ["a devastating cloudburst", "a record-breaking downpour"]),
    (r"\b(?:light )?drizzle\b",
        ["a violent cloudburst", "a torrential downpour"]),
    (r"\b(?:heavy |severe |minor |slight )?waterlogging\b",
        ["complete submersion of the district", "total inundation of the city"]),
    (r"\b(?:heavy |severe |minor )?waterlogged\b",
        ["completely submerged", "entirely underwater"]),
    (r"\b(?:severe |major |minor |flash )?flooding\b",
        ["total submersion of the district", "citywide inundation"]),
    (r"\bflooded\b",
        ["completely submerged", "washed away entirely"]),
    (r"\b(?:strong |gusty |high )?winds?\b",
        ["cyclonic winds", "hurricane-force winds"]),
    (r"\b(?:dense |thick )?fog\b",
        ["a total whiteout", "zero-visibility conditions"]),
    (r"\btraffic (?:jams?|congestion|disruption|snarls?)\b",
        ["a total collapse of all transport", "complete statewide gridlock"]),
    (r"\b(?:minor |slight |some )?delays?\b",
        ["a total shutdown", "a complete suspension of all services"]),
    (r"\b(?:orange |yellow |red |severe )?(?:weather )?(?:warning|alert|advisory)\b",
        ["a mandatory evacuation order", "an emergency mass-evacuation order"]),
    (r"\bhumidity\b",
        ["life-threatening humidity", "unsurvivable humidity"]),
]

# Scale words. Real reports hedge; fabrications rarely do.
SCALE = [
    (r"\bseveral\b",     ["hundreds of", "thousands of"]),
    (r"\bsome\b",        ["all", "every one of the"]),
    (r"\ba few\b",       ["hundreds of", "thousands of"]),
    (r"\bdozens\b",      ["thousands", "hundreds of thousands"]),
    (r"\bmany\b",        ["all", "every single"]),
    (r"\bparts of\b",    ["the entirety of", "every district of"]),
    (r"\bareas\b",       ["entire districts", "whole states"]),
]

# Real forecasts give lead time. Fabrications compress it to create panic.
# Each pattern swallows the whole time phrase - matching a bare "tomorrow"
# inside "through tomorrow evening" leaves a dangling "evening".
TIMING = [
    (r"\b(?:through |by |until |from )?tomorrow(?: evening| morning| night| afternoon)?\b",
        ["within the next 20 minutes", "in the next 15 minutes"]),
    (r"\b(?:over |for |in )?the next (?:two |three |four |few )?days?\b",
        ["in the next 20 minutes", "within the next half hour"]),
    (r"\b(?:over |in )?the (?:coming|next) week\b",
        ["in the next 20 minutes", "within the hour"]),
    (r"\b(?:over |during )?the weekend\b",
        ["within the hour", "in the next 20 minutes"]),
    (r"\b(?:is |are |was |were )?expected\b",
        ["is already underway", "is confirmed to be happening now"]),
    (r"\b(?:has |have )?forecasts?\b", ["confirms", "has confirmed"]),
    (r"\blikely\b", ["confirmed", "certain"]),
]

# Units and the range beyond which a value stops being physically plausible
# for India. The multiplier is chosen so the result clears that bar.
UNIT_RE = re.compile(
    r"(?<![\w.])(\d{1,4}(?:\.\d+)?)\s*(mm|cm|km/?h|kmph|%|C\b|°C|degrees?|feet|ft|lakh|crore)",
    re.IGNORECASE,
)


def _swap(text, table, rng):
    """Apply one random rule from `table`. Returns new text or None."""
    rules = list(table)
    rng.shuffle(rules)
    for pattern, options in rules:
        if re.search(pattern, text, re.IGNORECASE):
            return re.sub(pattern, rng.choice(options), text,
                          count=1, flags=re.IGNORECASE)
    return None


def _inflate_number(text, rng):
    """
    Multiply a measured value into impossibility, keeping its unit.

    Temperature is handled separately - multiplying 41C by 8 gives a number so
    absurd it becomes its own tell, so it is pushed just past the survivable
    range instead. The fabrication has to stay superficially readable.
    """
    matches = list(UNIT_RE.finditer(text))
    if not matches:
        return None
    m = rng.choice(matches)
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()

    if unit in ("c", "°c", "degree", "degrees"):
        if value < 20:          # probably not a temperature
            return None
        new = rng.randint(58, 71)
    elif unit == "%":
        new = rng.randint(180, 900)
    elif unit in ("mm", "cm"):
        new = int(max(value, 1) * rng.choice([12, 20, 35, 60]))
    elif unit in ("km/h", "kmh", "kmph"):
        new = rng.randint(280, 480)
    else:
        new = int(max(value, 1) * rng.choice([15, 40, 100]))

    return text[:m.start(1)] + str(new) + text[m.end(1):]


STRATEGIES = [
    ("number",   _inflate_number),
    ("severity", lambda t, r: _swap(t, SEVERITY, r)),
    ("scale",    lambda t, r: _swap(t, SCALE, r)),
    ("timing",   lambda t, r: _swap(t, TIMING, r)),
]


# Word salad that two colliding edits can produce, e.g. SCALE turning
# "several" into "hundreds of" right where SEVERITY turned "delays" into
# "a complete suspension of all services". Rejected rather than shipped -
# incoherent grammar is a tell the model would learn instead of the claim.
GARBLED_RE = re.compile(
    r"\b(?:hundreds|thousands|millions) of (?:a|an|the) \b"
    r"|\bof (?:a|an) (?:total|complete|mandatory|emergency)\b"
    r"|\b(?:several|some|many|few|dozens|all|every) (?:a|an) \b"
    r"|\ball (?:a|an) \b",
    re.IGNORECASE,
)


def _fix_case(original: str, edited: str) -> str:
    """
    Restore sentence-initial capitalisation.

    Replacing a phrase at position 0 leaves a lowercase first letter, and a
    text starting lowercase is a giveaway the model would learn instead of
    the claim. Cheap to fix, expensive to leave.
    """
    if edited and original and original[0].isupper() and edited[0].islower():
        return edited[0].upper() + edited[1:]
    return edited


def corrupt(text: str, rng: random.Random, max_edits: int = None):
    """
    Return (corrupted_text, [strategies_used]) or (None, []) if nothing applied.

    One or two edits, never more. The whole point is that the result stays
    almost identical to its source - a heavily rewritten post drifts back
    toward being a different kind of text, which is the failure we are
    correcting.
    """
    if not text or len(text) < 40:
        return None, []

    # Usually one edit. Two edits sometimes collide - "several delays" became
    # "thousands of a total shutdown" - and the resulting word salad is its own
    # tell. One well-placed change is a harder example than two clumsy ones.
    if max_edits is None:
        max_edits = 2 if rng.random() < 0.35 else 1

    order = list(STRATEGIES)
    rng.shuffle(order)

    out, used = text, []
    for name, fn in order:
        if len(used) >= max_edits:
            break
        try:
            attempt = fn(out, rng)
        except Exception:
            attempt = None
        if attempt and attempt != out:
            out, _ = attempt, used.append(name)

    if not used or out == text:
        return None, []
    if GARBLED_RE.search(out):
        return None, []
    return _fix_case(text, out), used


def build_from_real(rows: list, seed: int = 20260830, target: int = None):
    """
    rows: dicts with at least 'text', ideally 'dedup_hash', 'city', 'state',
          'event_category', 'posted_at'.

    Returns a list of corrupted rows. Each keeps its source's dedup_hash so
    the pair cannot straddle the train/test split - without that, the model
    would see one half of a near-identical pair in training and be tested on
    the other, which inflates the score to meaninglessness.
    """
    rng = random.Random(seed)
    pool = list(rows)
    rng.shuffle(pool)

    out, seen = [], set()
    for src in pool:
        if target is not None and len(out) >= target:
            break
        text, used = corrupt(src.get("text", ""), rng)
        if not text or text in seen:
            continue
        seen.add(text)
        row = dict(src)
        row.update({
            "text": text,
            "ml_label": 1,
            "source": "corrupted",
            "contradiction": "",
            "corruption": ",".join(used),
        })
        out.append(row)
    return out
