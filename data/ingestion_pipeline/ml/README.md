# ml/ — training set + baseline

Two scripts. Put this folder at `data/ingestion_pipeline/ml/`.

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install scikit-learn
```

## Run

```powershell
cd C:\Users\jagri\OneDrive\Desktop\onyx-weather\data\ingestion_pipeline
.\.venv\Scripts\python.exe ml\build_dataset.py
.\.venv\Scripts\python.exe ml\train_baseline.py
.\.venv\Scripts\python.exe ml\train_baseline.py --target contradiction
```

`build_dataset.py` reads Supabase directly, so `backend\.env` must exist.

## What comes out

**`ml/dataset.csv`** — one row per training example.

| column | meaning |
|---|---|
| `text` | the cleaned text. **This is the only input the model gets.** |
| `ml_label` | 0 = collected from a real service, 1 = fabricated by our generator |
| `contradiction` | 0 = claim agrees with measurement, 1 = measurement denies it, blank = unknown |
| `event_category` | flooding / rainfall / heatwave / … |
| `city`, `state`, `posted_at` | context, not features |
| `source` | **never** feed this to a model — see below |
| `dedup_hash` | what the split is grouped by |
| `split` | train / test, already assigned |
| `measured_*` | what Open-Meteo actually recorded, for auditing a contradiction label |

**`ml/report.txt`** — class balance and the leakage checks. Read it before
trusting any score.

## The two labels, and why there are two

`ml_label` is what the problem statement asks for. Its weakness is structural:
you cannot collect labelled misinformation, so class 1 has to be fabricated by
us. A model trained on it learns *"does this look like our generator"*, which
is a real skill but not the one we're claiming.

`contradiction` is derived entirely from real data. For every located social
post, the script asks Open-Meteo what actually happened at that city in the
three hours before the post, and compares it against what the post claims:

- claims flooding, under 0.5 mm fell → **contradicted**
- claims flooding, 10 mm or more fell → **consistent**
- anything in between → **left blank**

That gap is deliberate. A post saying "heavy rain" when 4 mm fell is neither
a lie nor a confirmation, and forcing it into a class teaches the model noise.

It's a sparse label — most rows come back blank — but every one of them is
evidence a judge can check. *"This post claims flooding in Jaipur; Open-Meteo
recorded 0.0 mm there that hour"* survives questioning. *"Our generator wrote
it"* does not.

## Rules that are not optional

**Never use `source`, `author` or `verification_status` as features.** Every
class-1 row has `source='synthetic'`. A model given that column scores 100%
and has learned nothing at all. The CSV carries them for auditing only.

**Never split randomly.** Use the `split` column. Near-duplicate posts share a
`dedup_hash`, and if one copy is in train and its twin is in test, the model
has already seen the answer.

**Treat >95% accuracy as a bug report.** At this dataset size that is a leak,
not a result. `train_baseline.py` prints the words driving each prediction —
if the top signals are artefacts (link fragments, a stock phrase, punctuation)
rather than meaning, the model found a shortcut.

## What the scripts already defend against

- **HTML and URL artefacts** — checked per class, flagged if the rates differ
- **Length** — synthetic text runs longer than real posts, and a model can
  score well on character count alone. `build_dataset.py` over-generates and
  keeps the subset whose lengths track the genuine rows. `--no-match-length`
  turns this off if you want to see the leak for yourself.
- **Vocabulary** — prints words that appear in one class and essentially never
  in the other
- **Identical text on both sides of a label** — reported loudly
- **Group-aware splitting** — on `dedup_hash`

None of this makes the dataset good. It makes its weaknesses visible, which is
the part that matters when someone asks how you validated it.

## Honest expectations

With roughly 200 genuine rows, expect the baseline around 0.80–0.92 on
`ml_label`. Higher than that, check the top features before celebrating.

`contradiction` will start with very few labelled rows — it only fires on
located, recent, weather-asserting posts. It grows every time the pipeline
runs. Leave the scheduler on overnight and re-run `build_dataset.py`.

## Next step, if the baseline holds up

Fine-tune DistilBERT on the same CSV and the same split. The baseline number
is what tells you whether the transformer earned its place — if it doesn't
clearly beat logistic regression, ship the logistic regression.
