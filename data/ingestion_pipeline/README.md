# Onyx — Weather Data Ingestion Pipeline

Collects real-time weather-related information about India from multiple public
sources, cleans and normalizes it, and stores everything in one SQLite database
ready for downstream ML (fake-report detection, dedup, event classification).

```
connectors/  →  cleaning.py  →  db.py                →  export (CSV/JSON)
(fetch raw)     (normalize)     (weather_reports.db)     (handoff to ML)
```

---

## Quick start

```
cd weather_pipeline

# 1. Create a virtual environment
python -m venv .venv
```

### 2. Activate it — THE COMMAND DEPENDS ON YOUR TERMINAL

This is the step people get wrong. Pick the row that matches what you're
actually typing into:

| Terminal | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows **Git Bash** | `source .venv/Scripts/activate` |
| Windows CMD | `.venv\Scripts\activate.bat` |
| macOS / Linux | `source .venv/bin/activate` |

**You'll know it worked when your prompt starts with `(.venv)`.**

Note the Git Bash row: it uses forward slashes and `Scripts` (not `bin`).
Running the PowerShell command in Git Bash fails with
`.venvScriptsActivate.ps1: command not found`, because bash eats the
backslashes.

If PowerShell blocks activation with a red "running scripts is disabled"
error, run this once, then retry:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### 3. The rest is the same everywhere

```
# Install dependencies
pip install -r requirements.txt

# Create the database
python main.py init-db

# Collect data
python main.py fetch

# See what you got
python main.py stats
```

**No API keys are required.** Every source that runs by default is fully open.

---

## Sources

| Source | What it pulls | Auth needed? |
|---|---|---|
| **openmeteo** | Live measured conditions for ~51 Indian cities | No |
| **mastodon** | Public posts on weather hashtags across instances | No |
| **rss** | Weather articles from 28 Indian news/weather feeds | No |
| **bluesky** | Public posts matching weather hashtags | Yes (free) |
| **citizen** | Reports submitted through the intake queue | No |

### A note on Bluesky

Bluesky's **public** search endpoint returns `403 Forbidden` for every
unauthenticated query, despite their docs saying it shouldn't - a known
upstream bug: https://github.com/bluesky-social/bsky-docs/issues/332

The connector works around this by authenticating instead. You need a free
Bluesky account (email only, no phone number) and an **app password** from
Settings -> Privacy and Security -> App Passwords. App passwords are
revocable and can't change your email or delete your account, so they're
safe to put in a `.env`.

Without credentials, Bluesky skips itself with a clear message rather than
failing the run.

### Sources that were evaluated and dropped

**Reddit** - Reddit closed self-serve app creation for its Data API. New apps
now require a manually reviewed request gated on moderation use cases, which
an analytics pipeline doesn't qualify for.

**Telegram** - `my.telegram.org` returns a bare "ERROR" on app creation with
no explanation. This is a widespread, unresolved issue
(https://github.com/tdlib/telegram-bot-api/issues/597) that Telegram closed
as "not planned". No reliable workaround exists.

**Twitter/X** - no usable free read/search tier; paid plans start around
$200/month, and scraping violates their terms.

## Commands

```powershell
python main.py init-db                  # create the database
python main.py fetch                    # collect from all default sources
python main.py fetch --source rss       # collect from one (or "rss,mastodon")
python main.py stats                    # row counts by source
python main.py purge-demo --dry-run     # list any sample rows in the DB
python main.py purge-demo               # remove them
python main.py purge-old --dry-run      # list rows older than the age cutoff
python main.py purge-old                # remove them
python main.py purge-unlocated --dry-run  # list rows with no Indian state
python main.py purge-unlocated            # remove them
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

## What gets filtered out

Three filters run at insert time. Each reports a count in the `fetch` output,
so nothing is dropped silently.

| Filter | Config | Counter |
|---|---|---|
| Content older than 7 days | `MAX_CONTENT_AGE_HOURS = 168` | `too_old=N` |
| Not locatable in India | `REQUIRE_INDIAN_LOCATION = True` | `no_location=N` |
| Unparseable timestamp | *(reported, not dropped)* | `no_date=N` |

### Why the India filter matters

Hashtag timelines are global. A search for `#rain` returns Manchester and
Melbourne alongside Mumbai. On a national platform those rows pollute the
dashboard's location filters and hand the ML stage irrelevant examples, so a
record is dropped unless `cleaning.guess_location()` resolves an Indian state
for it.

### How location detection works

Keyword matching against `INDIAN_CITIES` (319 places) and `INDIAN_STATES`.
The list covers metros and their older names (Bombay, Calcutta, Madras,
Bengaluru, Vizag, Trivandrum), all state and UT capitals, tier-2 and tier-3
cities, regions that appear in weather reporting (Konkan, Vidarbha,
Saurashtra, Wayanad, Sundarbans), and the metro localities where waterlogging
actually gets reported (Andheri, Kurla, Koramangala, Gachibowli, Thane).

**Ambiguous names need corroboration.** Some Indian place names are also
common Hindi words or foreign cities:

| Text | Naive result | Actual result |
|---|---|---|
| `wo chala gaya tha barish me` | Gaya, Bihar | dropped |
| `vegetables at the mandi` | Mandi, HP | dropped |
| `Salem Oregon flooding` | Salem, **Tamil Nadu** | dropped |
| `Salem records 80mm, Tamil Nadu on alert` | Salem, Tamil Nadu | Salem, Tamil Nadu |

Names in `AMBIGUOUS_PLACES` (in `cleaning.py`) only count when the text also
shows an India signal — an explicit India/IMD mention, or a second
unambiguous Indian place.

**If you're losing rows you want**, widen `INDIAN_CITIES` rather than turning
the filter off. A genuinely Indian post that names no place at all ("heavy
rain here since morning") is indistinguishable from a foreign one, and no
amount of tuning fixes that.

### Filters only apply to new rows

All three run at insert time. Rows already in the database are untouched, so
after changing a setting run the matching purge command to bring existing
data in line.

## Output format

Everything lands in **one flat table**, `weather_reports`, inside
`weather_reports.db` — a single SQLite file. No server required. Open it with
DB Browser for SQLite, the `sqlite3` CLI, `pandas.read_sql`, or VS Code's SQLite
extension.

Every source produces the same 23 columns, so one loader handles all of them:

| Column | Meaning |
|---|---|
| `id` | internal row ID |
| `source` | `openmeteo` / `mastodon` / `rss` / `bluesky` / `citizen` |
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
  This is the single biggest lever on how much data survives the India
  filter — a post about a place that isn't listed gets discarded. Open-Meteo
  also automatically polls anything added here.
  If the name doubles as a common word or foreign city, add it to
  `AMBIGUOUS_PLACES` in `cleaning.py` too.
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

**`.venvScriptsActivate.ps1: command not found`** — you're in Git Bash but ran
the PowerShell activate command. Bash strips the backslashes. Use
`source .venv/Scripts/activate` instead (see the table in Quick start).

**`running scripts is disabled on this system`** — see the
`Set-ExecutionPolicy` line in Quick start.

**`module has no attribute 'fetch'`** — a connector file is truncated or empty.
Check its length; every connector should be well over 100 lines.

**A source returns `fetched=0`** — usually genuine (nothing new matched), not a
bug. `openmeteo` returning 0 is the exception and means the API call failed —
check the console for the error above it.
