# Hybrid scoring layer

One blended `hybrid_score` per report, plus a JSON breakdown of what made it.

```
python ml/score_worker.py --limit 50      # 1. classifier
python verify_worker.py --limit 400 --all # 2. measurement cross-reference
python hybrid/hybrid_worker.py --all      # 3. blend  <- new
```

Writes three columns, added automatically on first run:

| column | meaning |
|---|---|
| `hybrid_score` | 0–1, or NULL when nothing could be evaluated |
| `hybrid_signals` | JSON: every signal, its weight, its contribution, the driver |
| `verdict` | `fake` ≥ 0.70, `suspect` ≥ 0.40, else `ok`; `unchecked` when NULL |

## The four signals

| signal | weight | where it comes from |
|---|---|---|
| `model` | 0.40 | DistilBERT `fake_probability` |
| `measurement` | 0.35 | `measurement_check` vs Open-Meteo |
| `physics` | 0.15 | **new** — recorded extremes, place-independent |
| `source` | 0.10 | **new** — author handle credibility |

**Missing signals are dropped and the weights renormalised**, never treated
as zero. This is the fix for the bug that made the Mumbai snowfall post read
`ok`: the measurement check had abstained, and abstention was being scored as
innocence. A post with only a model score is now judged on the model score
alone, and its breakdown says so.

## What the two new rules add

**Physics** catches claims that are false everywhere, always — `800 km/h
winds`, `62C`. No API, no location, no timestamp, no model needed, so it
still fires when everything else has failed. It has two bands and words them
differently, because 310 km/h is implausible while 800 km/h is impossible and
saying "the record is 408" about a 310 claim rebuts itself.

Note that `-15C in Mumbai` scores **zero** here, correctly — minus fifteen is
not physically impossible on earth, it is impossible *in Mumbai*, which is
the measurement layer's job. The two rules do not overlap.

**Source** scores the author handle. Deliberately weak: an unknown handle is
the normal state of a citizen report, so unknown sits at 0.50 (neutral) with
the smallest weight. It breaks ties, it never decides.

## Deliberately not included

VayuDrishti has a sensationalism keyword score (`apocalypse`, `HAARP`, ALL
CAPS, `!!!`). We don't, because DistilBERT already reads exactly that — tone,
urgency, capitalisation, severity language. Adding keywords on top would
count the same evidence twice and make a loud-but-true post look worse than
the evidence supports.

## Worked examples

```
0.81   FAKE     driver=model
       URGENT: 310 kmph cyclonic winds tearing through Visakhapatnam
       classifier 0.900; measurements contradict; claims 310 km/h winds -
       implausibly high, Indian cyclone gusts reach ~260; @cycloneupdates
       unrecognised

0.56   SUSPECT  driver=measurement
       IMD has confirmed Mumbai will experience snowfall ... -15C
       classifier 0.120; measurements contradict the claim;
       @weatherguy882910 looks like a throwaway handle

0.80   FAKE     driver=physics
       Winds of 800 km/h recorded near Chennai coast
       claims 800 km/h - physically impossible, strongest gust ever
       recorded on earth is 408 km/h        (no model score, no measurement)

0.03   OK       driver=model
       Heavy rainfall warning for Mumbai and Thane districts today.
       classifier 0.050; measurements agree; @IMD_Mumbai official handle

None   UNCHECKED
       no model score, no measurement, no impossible figures
```

The third one is the argument for the layer: a post nothing else had looked
at, caught on the text alone.

## Postgres

The worker adds its columns with `ALTER TABLE ... ADD COLUMN`, which SQLite
and Postgres both accept, so the local database needs no migration. For
Supabase, also add them to `backend/app/models/weather_report.py` and
generate a revision so the schema file stays authoritative — see
`alembic_add_hybrid.py`.

## Tuning

`WEIGHTS`, `FAKE_AT` and `SUSPECT_AT` are at the top of `hybrid.py`. The
thresholds are set where a single signal firing alone lands in `suspect` and
two agreeing signals land in `fake`, which keeps the precision-first
behaviour the classifier was tuned for. Change them together, then rerun
`hybrid_worker.py --all` — every score is derived, so nothing has to be
migrated.
