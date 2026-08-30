"""
build_dataset.py
----------------
Builds the ML training set from the live Supabase table, with TWO labels.

    python ml/build_dataset.py
    python ml/build_dataset.py --no-measurements   (skip the Open-Meteo lookup)

Why two labels
--------------
The problem statement asks for fake detection. The honest difficulty is that
you cannot collect labelled misinformation - nothing in the wild arrives
tagged as fake. So class 1 has to be fabricated by our own generator, and a
model trained on it learns "does this look like our generator", not "is this
misinformation". That is worth building, but it is not worth *only* building.

So this script produces two independent targets:

  ml_label          0 = collected from a real service
                    1 = fabricated by generate_synthetic.py
                    Fully labelled, but class 1 is artificial.

  contradiction     0 = the claim agrees with what the weather actually did
                    1 = the claim is contradicted by measurement
                    (blank) = no measurement available, or too close to call
                    Sparse, but every label is derived from real data.

The second one is the defensible one. "This post claims flooding in Jaipur;
Open-Meteo recorded 0.0 mm there that hour" is evidence a judge can check.
"Our generator wrote it" is not.

Output
------
    ml/dataset.csv     one row per example, with a `split` column
    ml/report.txt      leakage checks and class balance - READ THIS

Both labels live in one file so you can train either target, or both, from
the same split without leaking rows between train and test.
"""

import argparse
import csv
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

# Run from the repo root or from ml/ - either works.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PIPELINE = os.path.dirname(_HERE)
if _PIPELINE not in sys.path:
    sys.path.insert(0, _PIPELINE)

import db                                   # noqa: E402
from cleaning import normalize_record       # noqa: E402
from generate_synthetic import build_records  # noqa: E402
from hard_negatives import build_from_real   # noqa: E402

# Sources whose text was written by an actual human. Open-Meteo is excluded
# on purpose: its rows are one templated sentence with numbers swapped in, and
# including them makes a template-detector that scores 99% and detects nothing.
HUMAN_SOURCES = {"mastodon", "rss", "bluesky", "citizen"}
MEASUREMENT_SOURCE = "openmeteo"

OUT_CSV = os.path.join(_HERE, "dataset.csv")
OUT_REPORT = os.path.join(_HERE, "report.txt")

URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
HTML_RE = re.compile(r"<[^>]+>|&[a-z]+;|&#\d+;", re.IGNORECASE)

FIELDS = [
    "text", "ml_label", "contradiction", "event_category",
    "city", "state", "posted_at", "source", "dedup_hash", "split",
    "measured_precip_mm", "measured_temp_c", "measured_wind_kmh",
    "corruption",
]


# ---------------------------------------------------------------------------
# 1. Pull the real rows
# ---------------------------------------------------------------------------

def load_rows():
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT source, text_clean, event_category_guess, city, state,
                       latitude, longitude, posted_at, dedup_hash
                FROM weather_reports
                WHERE text_clean IS NOT NULL AND text_clean <> ''
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# 2. Measured conditions, for the contradiction label
# ---------------------------------------------------------------------------

def fetch_history(coords: list, days: int = 7) -> dict:
    """
    One batched call to Open-Meteo for hourly history at every coordinate.

    `past_days` on the forecast endpoint returns recent observed/analysed
    hours, which is exactly the window our age filter allows (168 h). The
    archive endpoint is not used because it lags several days behind, and
    everything in this table is younger than that.

    Returns {(lat, lon): {datetime_utc: {precip, temp, wind, code}}}
    """
    import requests

    out = {}
    BATCH = 40
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
        print(f"  history batch {i // BATCH + 1}: {len(chunk)} locations")
    return out


def _window(series: dict, when: datetime, hours: int = 24):
    """
    Every reading in the `hours` leading up to `when`.

    24 hours, not 3. A post written at 9am about last night's flooding is
    talking about the whole night's rain. Comparing it against 6am-9am makes
    an honest report look like a lie, and that mistake alone made 94% of the
    first run come back "contradicted".
    """
    lo = when - timedelta(hours=hours)
    return [v for ts, v in series.items() if lo <= ts <= when]


def contradiction_label(category, series, when):
    """
    Compare a claim against measurement. Returns (label, precip, temp, wind).

    label 1  contradicted   - the claim asserts something the instruments deny
    label 0  consistent     - measurement supports it
    label None              - no reading, or the value falls in the gap between
                              the two thresholds

    The gap is deliberate and it is the most important part of this function.
    A post saying "heavy rain" when 4 mm fell is neither a lie nor a
    confirmation, and forcing it into a class would teach the model noise.
    Only label what is clear.
    """
    if not series or not when:
        return None, None, None, None

    readings = _window(series, when)
    if not readings:
        return None, None, None, None

    precip = sum((r["precip"] or 0.0) for r in readings)
    temps = [r["temp"] for r in readings if r["temp"] is not None]
    winds = [r["wind"] for r in readings if r["wind"] is not None]
    temp = max(temps) if temps else None
    wind = max(winds) if winds else None
    codes = [r["code"] for r in readings if r["code"] is not None]

    label = None
    if category == "flooding":
        # Over a full day. Bone dry means the claim cannot be true; a real
        # soaking means it plausibly is. Anything between stays unlabelled.
        if precip < 1.0:
            label = 1
        elif precip >= 20.0:
            label = 0
    elif category == "rainfall":
        if precip < 0.5:
            label = 1
        elif precip >= 5.0:
            label = 0
    elif category == "heatwave":
        if temp is not None:
            if temp < 32.0:
                label = 1
            elif temp >= 38.0:
                label = 0
    elif category == "strong_wind":
        if wind is not None:
            if wind < 12.0:
                label = 1
            elif wind >= 28.0:
                label = 0
    elif category == "thunderstorm":
        # WMO 95/96/99 are the thunderstorm codes.
        if codes:
            if any(c in (95, 96, 99) for c in codes):
                label = 0
            elif precip < 0.2:
                label = 1

    return label, round(precip, 2), temp, wind


# ---------------------------------------------------------------------------
# 3. Leakage checks
# ---------------------------------------------------------------------------

def _rate(texts, pattern):
    if not texts:
        return 0.0
    return 100.0 * sum(1 for t in texts if pattern.search(t)) / len(texts)


def leakage_report(rows, label_key, say):
    pos = [r["text"] for r in rows if r[label_key] == 1]
    neg = [r["text"] for r in rows if r[label_key] == 0]
    if not pos or not neg:
        say(f"  {label_key}: not enough of both classes to check")
        return

    say(f"  class 0: {len(neg):>5}    class 1: {len(pos):>5}")

    # Artefacts that survived cleaning. Any gap here is a free giveaway - the
    # model finds it before it ever looks at the words.
    for name, pat in (("contains URL", URL_RE), ("contains HTML", HTML_RE)):
        a, b = _rate(neg, pat), _rate(pos, pat)
        flag = "  <-- LEAK" if abs(a - b) > 8 else ""
        say(f"  {name:<16} class0 {a:5.1f}%   class1 {b:5.1f}%{flag}")

    # Length. If the two classes have visibly different length distributions,
    # a model can score well on character count alone and learn no language.
    la = sorted(len(t) for t in neg)
    lb = sorted(len(t) for t in pos)
    ma, mb = la[len(la) // 2], lb[len(lb) // 2]
    flag = "  <-- LEAK" if abs(ma - mb) > 40 else ""
    say(f"  median length    class0 {ma:5d}     class1 {mb:5d}{flag}")

    # Words that appear in one class and essentially never in the other. A few
    # are expected; a long list of ordinary words means the vocabularies are
    # disjoint and the task is trivially separable.
    def vocab(texts):
        c = Counter()
        for t in texts:
            c.update(set(re.findall(r"[a-z]{3,}", t.lower())))
        return c

    va, vb = vocab(neg), vocab(pos)
    giveaways = [
        w for w, n in vb.most_common(400)
        if n >= max(5, 0.10 * len(pos)) and va.get(w, 0) <= 0.01 * len(neg)
    ][:12]
    if giveaways:
        say(f"  class-1-only words: {', '.join(giveaways)}")

    # Identical text on both sides of the label is a straight contradiction.
    overlap = set(neg) & set(pos)
    if overlap:
        say(f"  !! {len(overlap)} identical texts appear in BOTH classes")


# ---------------------------------------------------------------------------
# 4. Group-aware split
# ---------------------------------------------------------------------------

def assign_splits(rows, test_frac=0.25, seed=42):
    """
    Split by dedup_hash, never by row.

    Near-duplicate posts share a dedup_hash. If one copy lands in train and
    another in test, the model has effectively seen the test set and the score
    is inflated. Grouping by hash makes the test set genuinely unseen.
    """
    rng = random.Random(seed)
    groups = defaultdict(list)
    for r in rows:
        groups[r["dedup_hash"] or id(r)].append(r)

    keys = sorted(groups)
    rng.shuffle(keys)
    cut = int(len(keys) * (1 - test_frac))
    for i, k in enumerate(keys):
        split = "train" if i < cut else "test"
        for r in groups[k]:
            r["split"] = split
    return len(keys)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Build the ML training set")
    ap.add_argument("--no-measurements", action="store_true",
                    help="skip the Open-Meteo lookup (no contradiction label)")
    ap.add_argument("--fake-ratio", type=float, default=1.0,
                    help="synthetic rows per genuine row (default 1.0 = balanced)")
    ap.add_argument("--no-match-length", dest="match_length", action="store_false",
                    help="don't length-match template rows (leaves a length leak)")
    ap.add_argument("--negatives", choices=["hard", "template", "both"],
                    default="hard",
                    help="hard = corrupt real posts (default, honest); "
                         "template = the old generator (trivially separable, "
                         "scored 0.994 with logistic regression); both = mix")
    ap.add_argument("--seed", type=int, default=20260830)
    args = ap.parse_args()

    lines = []
    def say(s=""):
        print(s)
        lines.append(s)

    say("=" * 64)
    say("ONYX TRAINING SET")
    say("=" * 64)

    # --- genuine -----------------------------------------------------------
    say("\n[1/5] reading Supabase")
    all_rows = load_rows()
    human = [r for r in all_rows if r["source"] in HUMAN_SOURCES]
    measured = [r for r in all_rows if r["source"] == MEASUREMENT_SOURCE]
    say(f"  {len(all_rows)} rows total")
    say(f"  {len(human)} human-written  ({', '.join(sorted(HUMAN_SOURCES))})")
    say(f"  {len(measured)} Open-Meteo (excluded from training text - templated)")

    if len(human) < 40:
        say("\n  ! fewer than 40 human rows. Run the pipeline a few more times")
        say("    before trusting any score this produces.")

    dataset = [{
        "text": r["text_clean"],
        "ml_label": 0,
        "contradiction": "",
        "event_category": r["event_category_guess"] or "other",
        "city": r["city"] or "",
        "state": r["state"] or "",
        "posted_at": r["posted_at"].isoformat() if r["posted_at"] else "",
        "source": r["source"],
        "dedup_hash": r["dedup_hash"] or "",
        "measured_precip_mm": "",
        "measured_temp_c": "",
        "measured_wind_kmh": "",
        "corruption": "",
        "_lat": r["latitude"], "_lon": r["longitude"], "_when": r["posted_at"],
    } for r in human]

    # --- fabricated -------------------------------------------------------
    n_fake = int(len(human) * args.fake_ratio)

    if args.negatives in ("hard", "both"):
        say(f"\n[2/5] corrupting real posts into {n_fake} hard negatives")
        # Each fake is a real post with only its CLAIM changed - a number
        # inflated past plausibility, a severity word escalated, a forecast's
        # lead time compressed. Roughly three quarters of the tokens are
        # identical to the source, so there is no style difference for a model
        # to exploit; it has to judge whether the claim itself is credible.
        hard = build_from_real(dataset, seed=args.seed, target=n_fake)
        for row in hard:
            row.pop("split", None)
            dataset.append(row)
        say(f"  {len(hard)} written from {len(human)} sources")
        if hard:
            say("  sample:")
            for row in hard[:2]:
                say(f"    [{row['corruption']}] {row['text'][:110]}")

    if args.negatives in ("template", "both"):
        want = n_fake if args.negatives == "template" else n_fake // 3
        say(f"\n[2b/5] generating {want} template negatives")
        pool = []
        for raw in build_records(want * (4 if args.match_length else 1),
                                 days_back=7, seed=args.seed):
            norm = normalize_record(raw)
            if norm["text_clean"]:
                pool.append(norm)

        if args.match_length and pool:
            targets = sorted(len(d["text"]) for d in dataset
                             if d["ml_label"] == 0)
            pool.sort(key=lambda n: len(n["text_clean"]))
            chosen, used = [], set()
            for target_len in targets[:want]:
                best, best_gap = None, None
                for idx, cand in enumerate(pool):
                    if idx in used:
                        continue
                    gap = abs(len(cand["text_clean"]) - target_len)
                    if best_gap is None or gap < best_gap:
                        best, best_gap = idx, gap
                    if best_gap == 0:
                        break
                if best is not None:
                    used.add(best)
                    chosen.append(pool[best])
            pool = chosen
            say(f"  length-matched ({len(pool)} kept)")

        for norm in pool[:want]:
            dataset.append({
                "text": norm["text_clean"],
                "ml_label": 1,
                "contradiction": "",
                "event_category": norm["event_category_guess"] or "other",
                "city": norm["city"] or "",
                "state": norm["state"] or "",
                "posted_at": norm["posted_at"],
                "source": "synthetic",
                "dedup_hash": norm["dedup_hash"] or "",
                "measured_precip_mm": "", "measured_temp_c": "",
                "measured_wind_kmh": "", "corruption": "",
                "_lat": None, "_lon": None, "_when": None,
            })

    say(f"  class 1 total: {sum(1 for d in dataset if d['ml_label'] == 1)}")

    # --- contradiction -----------------------------------------------------
    if args.no_measurements:
        say("\n[3/5] measurement lookup skipped (--no-measurements)")
    else:
        say("\n[3/5] checking claims against measured conditions")
        coords = sorted({
            (round(d["_lat"], 3), round(d["_lon"], 3))
            for d in dataset
            if d["ml_label"] == 0 and d["_lat"] is not None and d["_lon"] is not None
        })
        say(f"  {len(coords)} distinct locations to look up")
        history = fetch_history(coords) if coords else {}

        # News feeds are excluded from this label entirely. An RSS item's
        # posted_at is when the article was PUBLISHED, not when the event
        # happened, and the article is often about somewhere else. Comparing
        # it against the weather at the resolved city at publication time
        # produces a confident "contradicted" for perfectly accurate
        # journalism - which is how `nepal` ended up as a top predictor.
        CLAIM_SOURCES = {"mastodon", "bluesky", "citizen"}

        counts = Counter()
        for d in dataset:
            if d["ml_label"] != 0 or d["_lat"] is None:
                counts["no location"] += 1
                continue
            if d["source"] not in CLAIM_SOURCES:
                counts["news (skipped)"] += 1
                continue
            key = (round(d["_lat"], 3), round(d["_lon"], 3))
            label, precip, temp, wind = contradiction_label(
                d["event_category"], history.get(key), d["_when"]
            )
            d["measured_precip_mm"] = "" if precip is None else precip
            d["measured_temp_c"] = "" if temp is None else temp
            d["measured_wind_kmh"] = "" if wind is None else wind
            if label is None:
                counts["unlabelled"] += 1
            else:
                d["contradiction"] = label
                counts["contradicted" if label else "consistent"] += 1

        for k in ("contradicted", "consistent", "unlabelled",
                  "news (skipped)", "no location"):
            say(f"  {k:<16} {counts[k]}")

        # Which categories are driving the label. If one category accounts for
        # nearly all of class 1, the label is measuring category rather than
        # truth and must not be trained on.
        by_cat = Counter((d["event_category"], d["contradiction"])
                         for d in dataset if d["contradiction"] != "")
        if by_cat:
            say("  breakdown by category (contradicted / consistent):")
            cats = sorted({c for c, _ in by_cat})
            for c in cats:
                say(f"    {c:<14} {by_cat[(c, 1)]:>4} / {by_cat[(c, 0)]:>4}")
            worst = max(cats, key=lambda c: by_cat[(c, 1)])
            share = by_cat[(worst, 1)] / max(sum(by_cat.values()), 1)
            if share > 0.7:
                say(f"  !! '{worst}' is {share:.0%} of all labels - this is")
                say("     measuring category, not truth. Do not train on it.")
        if counts["contradicted"] + counts["consistent"] < 30:
            say("  ! too few labelled to train on yet - this grows as the")
            say("    pipeline collects more located, recent social posts.")

    # --- split -------------------------------------------------------------
    say("\n[4/5] splitting")
    n_groups = assign_splits(dataset)
    tr = sum(1 for d in dataset if d["split"] == "train")
    say(f"  {n_groups} dedup groups -> train {tr} / test {len(dataset) - tr}")

    # --- checks ------------------------------------------------------------
    say("\n[5/5] leakage checks")
    say("\n  -- ml_label --")
    leakage_report(dataset, "ml_label", say)
    con = [d for d in dataset if d["contradiction"] != ""]
    if con:
        say("\n  -- contradiction --")
        for d in con:
            d["contradiction"] = int(d["contradiction"])
        leakage_report(con, "contradiction", say)

    say("\n  NOTE: `source` is perfectly separable from ml_label by")
    say("  construction - every class-1 row is 'corrupted' or 'synthetic'.")
    say("  That is expected and unfixable. It is exactly why source, author")
    say("  and verification_status must be excluded from the features.")

    # --- write -------------------------------------------------------------
    for d in dataset:
        for k in ("_lat", "_lon", "_when"):
            d.pop(k, None)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(dataset)

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    say(f"\nwrote {OUT_CSV}  ({len(dataset)} rows)")
    say(f"wrote {OUT_REPORT}")


if __name__ == "__main__":
    main()
