# Onyx — Weather Data Ingestion Pipeline

Collects real-time weather-related information about India from multiple public
sources, cleans and normalizes it, and stores everything in one SQLite database
ready for downstream ML (fake-report detection, dedup, event classification).

```
connectors/  →  cleaning.py  →  db.py                →  export (CSV/JSON)
(fetch raw)     (normalize)     (weather_reports.db)     (handoff to ML)
```

---

## Quick start (Windows / PowerShell)

```powershell
cd weather_pipeline

# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks that with a red "running scripts is disabled" error, run
this once, then retry the activate line:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

```powershell
# 2. Install dependencies
pip install -r requirements.txt

# 3. Create the database
python main.py init-db

# 4. Collect data
python main.py fetch

# 5. See what you got
python main.py stats
```

On macOS/Linux the only difference is `source .venv/bin/activate` in step 1.

**No API keys are required.** Every source that runs by default is fully open.

---

## Sources

| Source | What it pulls | Status |
|---|---|---|
| **openmeteo** | Live measured conditions for ~51 Indian cities | ✅ Always works |
| **mastodon** | Public posts on weather hashtags across instances | ✅ Working |
| **rss** | Weather articles from 28 Indian news/weather feeds | ✅ Working |
| **citizen** | Reports submitted through the intake queue | ✅ Working (empty until submissions arrive) |
| bluesky | Public hashtag search | ⚠️ Disabled — upstream bug |
| reddit | Weather posts from India subreddits | ⚠️ Disabled — access closed |

### Why two sources are disabled

Both connectors are **complete and functional**. They're excluded from the
default run because of platform-side access restrictions, not code problems:

- **Bluesky** — its public `searchPosts` endpoint returns `403 Forbidden` for
  every unauthenticated query, despite their own docs saying it shouldn't.
  Confirmed upstream bug: https://github.com/bluesky-social/bsky-docs/issues/332
  Re-enable by adding `"bluesky"` to `DEFAULT_SOURCES` in `pipeline.py` if it
  gets fixed.

- **Reddit** — Reddit has closed self-serve app creation for the legacy Data
  API. New apps now require a manually reviewed request gated on moderation use
  cases, which an analytics pipeline doesn't qualify for. The connector works
  the moment credentials exist; they just can't be provisioned on demand.

Run either explicitly with `--source bluesky` / `--source reddit` to test.

---

## Commands

```powershell
python main.py init-db                  # create the database
python main.py fetch                    # collect from all default sources
python main.py fetch --source rss       # collect from one (or "rss,mastodon")
python main.py stats                    # row counts by source
python main.py purge-demo --dry-run     # list any sample rows in the DB
python main.py purge-demo               # remove them
python main.py export --format csv --out exports/weather_reports.csv
python main.py export --format json --out exports/weather_reports.json
```

Re-running `fetch` is safe and cheap — rows are deduplicated by
`(source, source_post_id)`, so repeat runs only add genuinely new records.

### About `--demo`

`fetch --demo` reads the fixtures in `sample_data/` instead of calling live
APIs. It exists for developing without network access. **Don't run it against a
database holding real data** — it writes fake records that look real. If you
already did, `purge-demo` removes them safely (it matches exact IDs from the
fixture files, so it can only ever delete known-fake rows).

---

## Output format

Everything lands in **one flat table**, `weather_reports`, inside
`weather_reports.db` — a single SQLite file. No server required. Open it with
DB Browser for SQLite, the `sqlite3` CLI, `pandas.read_sql`, or VS Code's SQLite
extension.

Every source produces the same 23 columns, so one loader handles all of them:

| Column | Meaning |
|---|---|
| `id` | internal row ID |
| `source` | `openmeteo` / `mastodon` / `rss` / `citizen` / `bluesky` / `reddit` |
| `source_post_id` | the record's native ID on its platform |
| `source_url` | permalink back to the original |
| `author` | username/handle/outlet |
| `text_raw` | original text, untouched |
| `text_clean` | URLs and @mentions stripped, whitespace normalized |
| `hashtags` | comma-separated hashtags found in the text |
| `posted_at` | ISO-8601 timestamp the record was published/observed |
| `ingested_at` | ISO-8601 timestamp this pipeline collected it |
| `city` / `state` | best-guess Indian location, matched against a built-in list |
| `latitude` / `longitude` | coordinates for that location |
| `location_raw` | the text the location guess was derived from |
| `media_urls` | comma-separated photo/video URLs |
| `media_type` | `photo` / `video` / `image` / `none` |
| `event_category_guess` | `rainfall`, `flooding`, `thunderstorm`, `cyclone`, `heatwave`, `dust_storm`, `fog`, `strong_wind`, `other` |
| `language` | language code where the source provides one |
| `dedup_hash` | fingerprint of normalized text + city + date |
| `is_likely_duplicate` | `1` if this row's `dedup_hash` matched an existing row |
| `verification_status` | `unverified` / `verified` / `fake` |
| `raw_json` | the full original payload, so nothing is ever lost |

### Example rows

A **measured** record (Open-Meteo):

```
source                 openmeteo
source_post_id         chennai-2026-08-23T15:30
author                 Open-Meteo (numerical weather model)
text_clean             Observed conditions in Chennai, Tamil Nadu: thunderstorm.
                       Temperature 30.2 C, humidity 74%, precipitation 2.1 mm,
                       wind 22.8 km/h (gusts 38.4 km/h).
city / state           Chennai / Tamil Nadu
latitude / longitude   13.0827 / 80.2707
event_category_guess   thunderstorm
verification_status    verified
raw_json               {"measured": {"temperature_2m": 30.2, ...}}
```

A **claimed** record (social post):

```
source                 mastodon
source_url             https://mastodon.social/@puneupdates/112233445566
author                 puneupdates@mastodon.social
text_clean             Waterlogging reported near Pune station after two hours
                       of continuous rain. Traffic badly affected. #rain #Pune #IMD
hashtags               imd,pune,rain
city / state           Pune / Maharashtra
media_urls             https://example.com/media/pune_waterlogging.jpg
event_category_guess   flooding
verification_status    unverified
```

---

## Notes for the ML side

**`event_category_guess` and `is_likely_duplicate` are cheap first passes,
not answers.** Category comes from keyword matching (except Open-Meteo rows,
where it's derived from measured values), and the duplicate flag is an exact
hash of normalized text. They exist so the dashboard has something to show
immediately and so ML isn't starting from zero. Fuzzy/semantic dedup and real
classification are still yours to build.

**`verification_status` is the column to write back into.** Everything defaults
to `unverified`. The one exception is `openmeteo`, which self-marks `verified`
because those rows are measurements, not claims.

**Open-Meteo rows are ground truth for fake detection.** This is the useful
part: join a social report's `(city, posted_at)` against the `openmeteo` row for
the same city and time window. A post claiming "streets flooded in Jaipur" when
measured precipitation there is `0.0 mm` is a strong misinformation signal.
That turns verification from guesswork into a table join. The measured values
live in `raw_json` under `measured`.

**`raw_json` holds the untouched original payload** for every row, so if
normalization dropped a field you need, it's still there.

---

## Is it real-time?

Not on its own — it's **polling, not streaming**. Each `fetch` is a snapshot.
The data is fresh (Open-Meteo readings are at most ~15 minutes old), but the
database only changes when the command runs.

Everything needed for continuous collection is already in place: dedup makes
re-running safe and cheap, and `ingested_at` timestamps every row. To make it
genuinely continuous, schedule `python main.py fetch` every 10–15 minutes via
Windows Task Scheduler (or `cron` on macOS/Linux) and it will accumulate
without supervision.

---

## Extending it

- **New hashtags/keywords** → `WEATHER_HASHTAGS` / `WEATHER_KEYWORDS` in `config.py`
- **New cities** → `INDIAN_CITIES` in `config.py` (city → state, lat, lon).
  Open-Meteo automatically picks up anything added here.
- **New RSS feeds** → `RSS_FEEDS` in `config.py`. Dead feeds log a warning and
  are skipped, so a broad list is safe.
- **New source** → add `connectors/<name>_connector.py` exposing
  `fetch(demo=False)` that returns the raw-record shape documented in
  `connectors/__init__.py`, then register it in `pipeline.py`'s `CONNECTORS`
  and add it to `DEFAULT_SOURCES`.
- **Citizen report form** → `connectors/citizen_connector.submit_citizen_report()`
  is what a Flask/FastAPI endpoint should call; it writes to the queue this
  pipeline reads.
- **Postgres instead of SQLite** → see the note at the bottom of `db.py`. The
  schema was kept deliberately flat so the migration is small.

---

## Troubleshooting

**`can't open file 'main.py'`** — you're in the wrong folder. `cd weather_pipeline` first.

**`ModuleNotFoundError`** — the virtual environment isn't active. Your prompt
should start with `(.venv)`.

**`running scripts is disabled on this system`** — see the
`Set-ExecutionPolicy` line in Quick start.

**`module has no attribute 'fetch'`** — a connector file is truncated or empty.
Check its length; every connector should be well over 100 lines.

**A source returns `fetched=0`** — usually genuine (nothing new matched), not a
bug. `openmeteo` returning 0 is the exception and means the API call failed —
check the console for the error above it.
