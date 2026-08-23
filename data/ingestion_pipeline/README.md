# Onyx — Weather Data Ingestion Pipeline

Fetches real-time, weather-related posts about India (tagged `#IMD`, `#rain`,
etc.) from public sources, cleans/normalizes them, and stores them in a
single SQLite database ready to hand off to the ML teammate for
fake-detection, dedup, and final event classification.

## What it does

```
connectors/  →  cleaning.py  →  db.py (weather_reports.db)  →  export (CSV/JSON)
(fetch raw)     (normalize)      (single source of truth)      (handoff)
```

Sources wired up:

| Source    | What it pulls                                   | Auth needed? |
|-----------|--------------------------------------------------|--------------|
| Bluesky   | Public posts matching weather hashtags           | No           |
| Mastodon  | Public hashtag timelines on major instances      | No           |
| Reddit    | Weather-keyword posts from India-relevant subs   | Yes (free)   |
| RSS/news  | Weather-relevant articles from Indian news feeds | No           |
| Citizen   | Reports submitted through a local intake queue   | No           |

**Twitter/X was deliberately left out.** As of 2026 its API no longer has a
usable free read/search tier (paid tiers start around $200/month), and
scraping it violates its terms of service — not something to build for a
hackathon submission. If your team gets paid API access later, add a
`connectors/twitter_connector.py` following the same pattern as the others.

## Setup

```bash
cd weather_pipeline
pip install -r requirements.txt
cp .env.example .env   # then fill in Reddit credentials (see below)
python main.py init-db
```

Reddit is the only source that needs a key, and it's free:
1. Go to https://www.reddit.com/prefs/apps → "create another app..."
2. Type: **script**. Redirect URI: `http://localhost:8080` (unused, but required).
3. Copy the client ID (under the app name) and secret into `.env`.

## Running it

```bash
# No API keys yet, or just want to see it work end-to-end:
python main.py fetch --demo

# Live run, every source:
python main.py fetch

# Live run, just one source:
python main.py fetch --source bluesky
python main.py fetch --source reddit,mastodon

# Check what's in the DB:
python main.py stats

# Export for your ML teammate:
python main.py export --format csv --out exports/weather_reports.csv
python main.py export --format json --out exports/weather_reports.json
```

Re-running `fetch` is safe — records are deduplicated by `(source,
source_post_id)`, so nothing gets inserted twice from the same post. For
scheduled/repeated collection (real "real-time"), run `python main.py fetch`
on a cron job / scheduled task every few minutes.

## The output format

Everything lands in **one flat table**, `weather_reports`, in
`weather_reports.db` (plain SQLite — open it with DB Browser for SQLite,
`sqlite3` CLI, pandas' `read_sql`, or hand the file straight to your
teammate).

| Column                | Meaning                                                                 |
|------------------------|--------------------------------------------------------------------------|
| `id`                   | internal row ID                                                          |
| `source`               | `bluesky` / `mastodon` / `reddit` / `rss` / `citizen`                    |
| `source_post_id`       | the post's ID on its native platform                                     |
| `source_url`           | permalink back to the original post                                      |
| `author`               | username/handle (as public as the platform exposes)                      |
| `text_raw`             | original text, untouched                                                 |
| `text_clean`           | URLs/@mentions stripped, whitespace normalized                           |
| `hashtags`             | comma-separated hashtags found in the text                               |
| `posted_at`            | ISO-8601 timestamp the post was made                                     |
| `ingested_at`          | ISO-8601 timestamp we pulled it in                                       |
| `city` / `state`       | best-guess Indian city/state, matched against a built-in list            |
| `latitude` / `longitude` | best-guess coordinates for that city                                   |
| `location_raw`         | the raw text the location guess came from                                |
| `media_urls`           | comma-separated photo/video URLs                                         |
| `media_type`           | `photo` / `video` / `none`                                               |
| `event_category_guess` | rule-based guess: `rainfall`, `flooding`, `thunderstorm`, `cyclone`, `heatwave`, `dust_storm`, `fog`, `strong_wind`, `other` |
| `language`             | language code if the source provides one                                 |
| `dedup_hash`           | fingerprint of normalized text+city+date, for cheap duplicate detection  |
| `is_likely_duplicate`  | 1 if this row's `dedup_hash` matched an existing row already in the DB   |
| `verification_status`  | `unverified` by default — the ML pipeline / admin panel updates this later |
| `raw_json`             | the full original API payload, so nothing is ever permanently lost       |

**Important:** `event_category_guess` and `is_likely_duplicate` are cheap,
rule-based first passes (keyword matching / exact-text hashing) — they
exist so the dashboard has *something* to show immediately and so your ML
teammate isn't starting from zero. They are not a substitute for the real
ML classification, fuzzy dedup, and fake-report detection your teammate is
building; think of these columns as "pipeline's best guess, ML has final
say," and `verification_status` is exactly the column that guess should be
overwritten into once ML has run.

## Extending it

- **New hashtags/keywords:** edit `WEATHER_HASHTAGS` / `WEATHER_KEYWORDS` in `config.py`.
- **New cities:** add to `INDIAN_CITIES` in `config.py` (city → state, lat, lon).
- **New source:** add a `connectors/<name>_connector.py` with a `fetch(demo=False)`
  function returning the raw-record shape documented in `connectors/__init__.py`,
  then register it in `pipeline.py`'s `CONNECTORS` dict.
- **Citizen report form:** `connectors/citizen_connector.submit_citizen_report()`
  is the function a Flask/FastAPI form endpoint should call — it writes into the
  same queue file this pipeline reads from.
- **Postgres instead of SQLite:** see the note at the bottom of `db.py` — the
  schema was kept intentionally flat/boring so the migration is small.

## A note on this repo's testing

Live network calls to social platforms weren't reachable from the sandbox
this was built in (outbound access there is locked to package registries
only), so the pipeline was verified end-to-end using `--demo` mode with the
bundled sample fixtures in `sample_data/`. The live code paths (`_search_live`,
`_fetch_tag_live`, the PRAW calls, `feedparser.parse`) are standard,
documented calls against each platform's public API — but run a live
`fetch` yourself early and watch the console output, since APIs do change.
