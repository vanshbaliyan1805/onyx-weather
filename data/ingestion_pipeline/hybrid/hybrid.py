"""
hybrid.py
---------
Combines every signal into one score, and says what it was made of.

    score, breakdown = hybrid_score(
        ml=0.83, measurement_check="contradicted",
        text=..., author=..., source="mastodon")

Why a blend instead of the CASE statement
-----------------------------------------
The old verdict was a ladder of if-elses over two columns. It worked, but it
threw away magnitude: a post the model scored 0.51 and one it scored 0.99
both came out 'suspect', and nothing recorded which signal did the flagging.
On a dashboard that is the difference between "this is fake" and "this is
fake because it claims 310 km/h winds, the measured peak was 17, and the
account was made last week".

Missing signals are DROPPED AND THE WEIGHTS RENORMALISED, never treated as
zero. This is the single most important line in the file. Scoring an
unverifiable post as if the measurement said "innocent" is how the Mumbai
snowfall post came out 'ok' - the check had abstained, and abstention was
being read as a pass. Here, a post with only a model score is judged on the
model score alone, and its breakdown says so.
"""

import json

from rules import physical_implausibility, source_risk

# The model and the measurement carry most of the weight because they are the
# only two signals that look at THIS post in THIS place at THIS time. Physics
# is a backstop and source is a tiebreaker.
WEIGHTS = {
    "model":       0.40,
    "measurement": 0.35,
    "physics":     0.15,
    "source":      0.10,
}

# A measurement verdict is categorical; these are its numeric equivalents.
# 'unverifiable' maps to None rather than 0.5 on purpose - it means the check
# ran and could not judge, which is not weak evidence of innocence, it is no
# evidence at all.
MEASUREMENT_VALUE = {
    "contradicted":  1.0,      # fallback when no severity was recorded
    "agrees":        0.0,
    "unverifiable":  None,
}

# Above this, the measurement is not evidence to be weighed against the
# classifier - it is an answer. "-12C in Delhi" on a day that never dropped
# below 26.3C missed by 38 degrees; blending that with a model that scored
# 0.01 produced 0.47 and a verdict of 'suspect', which understates a
# measurement disagreeing by four and a half margins.
DECISIVE_MEASUREMENT = 0.95

FAKE_AT = 0.70
SUSPECT_AT = 0.40

# Where a physically impossible claim lands regardless of the other signals.
# Above FAKE_AT, because nothing a classifier or a thermometer says should be
# able to rescue "500C" - but not 1.0, so a row where the model AND the
# measurement also fired still scores higher and sorts above it.
IMPOSSIBLE_FLOOR = 0.85


def hybrid_score(ml=None, measurement_check=None, text=None, author=None,
                 source=None, severity=None):
    """
    Returns (score or None, breakdown dict).

    score is None only when nothing at all could be evaluated, which the
    caller should record as 'unchecked' rather than as a low score.
    """
    signals = {}

    if ml is not None:
        signals["model"] = {
            "value": round(float(ml), 4),
            "note": f"classifier scored {float(ml):.3f}",
        }

    mv = MEASUREMENT_VALUE.get(measurement_check)
    if mv is not None:
        # Severity grades HOW badly the claim missed. Rows checked before the
        # severity column existed fall back to the flat 1.0.
        if measurement_check == "contradicted" and severity is not None:
            mv = float(severity)
        signals["measurement"] = {
            "value": round(mv, 4),
            "note": (f"measurements contradict the claim"
                     + (f" (severity {mv:.2f})" if mv > 0 else "")
                     if measurement_check == "contradicted"
                     else "measurements agree with the claim"),
        }

    phys, phys_note = physical_implausibility(text)
    if phys > 0:
        # Only recorded when it fires. A zero here means "no impossible
        # number found", which is true of almost every post and would just
        # drag every score toward zero if it were counted as evidence.
        signals["physics"] = {"value": round(phys, 4), "note": phys_note}

    srisk, snote = source_risk(author, source)
    signals["source"] = {"value": round(srisk, 4), "note": snote}

    # Source alone is never enough. Without at least one substantive signal
    # the row is unscored, not innocent.
    substantive = {k for k in signals if k != "source"}
    if not substantive:
        return None, {"signals": signals, "verdict": "unchecked",
                      "reason": "no model score, no measurement, no "
                                "impossible figures"}

    total_w = sum(WEIGHTS[k] for k in signals)
    score = sum(WEIGHTS[k] * signals[k]["value"] for k in signals) / total_w

    # A claim that is physically impossible is not 15% of an argument, it is
    # the end of one. Weighted averaging cannot express that: "Mumbai is
    # experiencing a 500C heatwave" scored 0.011 from the classifier, and
    # 0.15 of certainty could not drag the blend above the suspect line, so
    # a self-evidently false post came out 'ok'. When physics reaches 1.0 the
    # score is floored instead of averaged.
    if signals.get("physics", {}).get("value", 0) >= 1.0:
        score = max(score, IMPOSSIBLE_FLOOR)
    if signals.get("measurement", {}).get("value", 0) >= DECISIVE_MEASUREMENT:
        score = max(score, IMPOSSIBLE_FLOOR)

    contributions = {
        k: round(WEIGHTS[k] * signals[k]["value"] / total_w, 4)
        for k in signals
    }
    top = max(contributions, key=contributions.get)

    return round(score, 4), {
        "signals": signals,
        "weights_used": {k: round(WEIGHTS[k] / total_w, 3) for k in signals},
        "contributions": contributions,
        "driver": top,
        "verdict": verdict_for(score),
    }


def verdict_for(score):
    if score is None:
        return "unchecked"
    if score >= FAKE_AT:
        return "fake"
    if score >= SUSPECT_AT:
        return "suspect"
    return "ok"


def explain(breakdown) -> str:
    """One human-readable line for the dashboard or a demo."""
    if breakdown.get("verdict") == "unchecked":
        return breakdown.get("reason", "not yet checked")
    parts = [f"{v['note']}" for k, v in breakdown["signals"].items()
             if v["value"] > 0.01 or k == "measurement"]
    return "; ".join(parts) if parts else "nothing flagged"


def to_json(breakdown) -> str:
    return json.dumps(breakdown, separators=(",", ":"), sort_keys=True)
