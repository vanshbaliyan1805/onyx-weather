================================================================================
ONYX WEATHER DATA INGESTION PIPELINE
Complete technical reference
================================================================================

This document explains every part of the pipeline: what each file does, what
every function is for, which external services are called and how, what
libraries are used and why, and the reasoning behind the design decisions.

Written for someone who has never seen the code and needs to understand,
modify, or defend it.

CONTENTS
--------
  1.  What this system does
  2.  The shape of the pipeline
  3.  Directory layout
  4.  Libraries used, and why
  5.  The unified record format
  6.  The database schema
  7.  config.py           — all tunable settings
  8.  connectors/         — one per data source
        8.1  openmeteo_connector.py
        8.2  mastodon_connector.py
        8.3  rss_connector.py
        8.4  bluesky_connector.py
        8.5  citizen_connector.py
  9.  cleaning.py         — normalization and enrichment
  10. db.py               — storage
  11. pipeline.py         — orchestration
  12. main.py             — the command line interface
  13. scheduler.py        — continuous collection
  14. query_examples.py   — reading the data
  15. The three filters
  16. How deduplication works
  17. Every external service called
  18. Sources evaluated and rejected
  19. Known limitations
  20. How to extend it


================================================================================
1. WHAT THIS SYSTEM DOES
================================================================================

It collects weather-related information about India from five public sources,
normalizes wildly different inputs into one consistent format, enriches each
record with location and event-type information, removes duplicates, and
stores everything in a single database for downstream use by a backend API,
a dashboard, and an ML verification stage.

The design goal throughout: a social media post, a news article, and a
numerical weather model reading should all end up as the same kind of row, so
that everything downstream writes one loader instead of five.


================================================================================
2. THE SHAPE OF THE PIPELINE
================================================================================

    ┌─────────────┐
    │ connectors/ │  Each talks to one external service and returns a list
    │             │  of "raw records" in a common intermediate shape.
    └──────┬──────┘
           │  list[dict]
           ▼
    ┌─────────────┐
    │ cleaning.py │  Normalizes text, extracts hashtags, resolves Indian
    │             │  location, categorizes the weather event, builds a
    │             │  dedup fingerprint. Produces the final 23-field record.
    └──────┬──────┘
           │  dict (23 keys)
           ▼
    ┌─────────────┐
    │  filters    │  Drop if too old / not in India. Count and report.
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │   db.py     │  Insert into SQLite. Skip exact duplicates, flag
    │             │  near-duplicates.
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │  export     │  CSV / JSON handoff, or direct queries.
    └─────────────┘

`pipeline.py` drives this loop. `main.py` wraps it in a CLI.
`scheduler.py` runs it on a repeating schedule.


================================================================================
3. DIRECTORY LAYOUT
================================================================================

  config.py               626 lines   All settings. The only file you should
                                      need to edit for normal changes.
  cleaning.py             292 lines   Normalization, location, categorization,
                                      dedup hashing, age filtering.
  db.py                   158 lines   SQLite schema and storage functions.
  pipeline.py             110 lines   Orchestration loop.
  main.py                 320 lines   CLI: init-db, fetch, stats, purges, export.
  scheduler.py            165 lines   Continuous two-schedule collector.
  query_examples.py        97 lines   Read-only inspection script.

  connectors/
    __init__.py            29 lines   Documents the raw-record contract.
    openmeteo_connector.py 229 lines  Measured weather, 289 cities.
    bluesky_connector.py   229 lines  Authenticated hashtag search.
    rss_connector.py       105 lines  28 news/weather feeds.
    mastodon_connector.py   94 lines  Public hashtag timelines.
    citizen_connector.py    87 lines  User-submitted report intake.

  sample_data/                        JSON fixtures for --demo mode.
  requirements.txt                    Three dependencies.
  .env.example                        Template for credentials.
  .env                                Actual credentials. GITIGNORED.
  weather_reports.db                  The database. GITIGNORED.
  scheduler.log                       Collector output. GITIGNORED.

Total: about 2,500 lines of Python.


================================================================================
4. LIBRARIES USED, AND WHY
================================================================================

THIRD-PARTY (requirements.txt — only three)

  requests >= 2.31
      HTTP client. Used by openmeteo, bluesky and mastodon connectors to call
      REST APIs. Chosen over raw urllib for automatic JSON decoding, session
      handling, timeouts and clear exception types (requests.Timeout,
      requests.ConnectionError) that the retry logic distinguishes between.

  feedparser >= 6.0
      RSS/Atom parser. Used by rss_connector. Handles the many malformed feeds
      in the wild, and — critically — exposes `published_parsed`, a
      pre-parsed time.struct_time, which sidesteps the RFC-2822 date problem
      described in section 9.

  python-dotenv >= 1.0
      Loads .env into os.environ at import time so credentials never live in
      source. Imported defensively in config.py inside a try/except, so the
      pipeline still runs if it isn't installed (you'd just export vars
      manually).

Notably NOT used: pandas, numpy, SQLAlchemy, any async framework. The data
volumes here are small enough that the standard library is faster to run and
far easier to debug.

STANDARD LIBRARY

  sqlite3        Database. No server, single file, ships with Python.
  json           Serializing raw_json payloads and reading fixtures.
  re             All text processing — hashtags, URLs, place-name matching.
  hashlib        SHA-256 for dedup fingerprints.
  datetime       Timestamp parsing, timezone handling, age calculation.
  email.utils    parsedate_to_datetime() — the RFC-2822 date parser.
  calendar       timegm() — converts struct_time to a UTC epoch.
  argparse       CLI argument parsing.
  contextlib     @contextmanager for database connection handling.
  os             Paths and environment variables.
  csv            Export.
  time           Sleeping and interval timing in the scheduler.
  signal         Clean Ctrl+C shutdown in the scheduler.
  collections    Counting in stats output.


================================================================================
5. THE UNIFIED RECORD FORMAT
================================================================================

There are TWO record shapes. Understanding the difference is the key to
understanding the codebase.

RAW RECORD — what a connector returns
  A loose intermediate dict. Each connector builds this from whatever the
  source gave it. Documented in connectors/__init__.py. Keys:

      source           str    short source name, e.g. "bluesky"
      source_post_id   str    the platform's own ID for this item
      source_url       str    permalink back to the original
      author           str    username / handle / outlet
      text_raw         str    the text
      posted_at        str    ISO-8601 timestamp
      location_hint    str    any location string the source supplied
      media_urls       list   photo/video URLs
      media_type       str    'photo' | 'video' | 'image' | 'none'
      language         str    language code if known
      extra            dict   anything else; becomes raw_json

  Two optional keys let a connector override cleaning's guesses:
      event_category       str   bypasses keyword guessing
      verification_status  str   bypasses the 'unverified' default

  Only openmeteo uses those, because only openmeteo *knows* — it derives
  category from measured numbers, and its rows are measurements rather than
  claims.

NORMALIZED RECORD — what goes into the database
  Produced by cleaning.normalize_record(). Exactly 23 fields matching the
  table schema. See section 6.


================================================================================
6. THE DATABASE SCHEMA
================================================================================

One flat table, `weather_reports`. Deliberately boring: no joins, no foreign
keys, no nested structures. Every source produces the same columns.

  id                    INTEGER  autoincrement primary key
  source                TEXT     openmeteo|mastodon|rss|bluesky|citizen
  source_post_id        TEXT     native ID on the source platform
  source_url            TEXT     permalink
  author                TEXT     handle / outlet
  text_raw              TEXT     original text, untouched
  text_clean            TEXT     URLs and @mentions stripped
  hashtags              TEXT     comma-separated, lowercased
  posted_at             TEXT     ISO-8601, when it was published/observed
  ingested_at           TEXT     ISO-8601, when we collected it
  city                  TEXT     resolved Indian city (nullable)
  state                 TEXT     resolved Indian state (nullable)
  latitude              REAL     coordinates for that place
  longitude             REAL
  location_raw          TEXT     the text the location was derived from
  media_urls            TEXT     comma-separated URLs
  media_type            TEXT     photo|video|image|none
  event_category_guess  TEXT     one of 9 categories
  language              TEXT     language code
  dedup_hash            TEXT     SHA-256 fingerprint
  is_likely_duplicate   INTEGER  0 or 1
  verification_status   TEXT     unverified|verified|fake (provenance/workflow)
  ml_label              INTEGER  0 = genuine, 1 = fabricated (TRAINING TARGET)
  raw_json              TEXT     complete original payload as JSON

  ml_label VS verification_status — NOT THE SAME THING
    verification_status is PROVENANCE. 'verified' on an Open-Meteo row means
    "this is a measurement", not "this claim was checked and held up".
    ml_label is the SUPERVISED TARGET: was this text fabricated.
    Training on verification_status would be label leakage — the model would
    learn Open-Meteo's sentence template and score ~99% detecting nothing.
    Everything collected here is ml_label = 0. Class 1 comes from a separate
    synthetic generator.
    CAVEAT: 0 means "we did not fabricate this", not "this is true".

CONSTRAINTS

  UNIQUE(source, source_post_id)
      The core dedup mechanism. The same item from the same source can
      physically only exist once, so re-running fetch is always safe.

INDEXES

  idx_reports_posted_at        date filtering (dashboard)
  idx_reports_city             location filtering (dashboard)
  idx_reports_event_category   event filtering (dashboard)
  idx_reports_dedup_hash       fast duplicate lookup on insert
  idx_reports_ml_label         splitting training classes

Those three dashboard filters — date, event, location — are exactly what the
problem statement asks for, and each has an index behind it.

WHY SQLITE
  Single file, no server, no configuration. You can email it, commit it,
  or open it in a GUI. For the hackathon handoff that matters more than
  concurrency. The schema is intentionally flat so migrating to PostgreSQL
  is a small change — see the note at the bottom of db.py.


================================================================================
7. config.py — ALL TUNABLE SETTINGS
================================================================================

Everything adjustable lives here. Nothing else should need editing for
routine changes.

PATHS
  BASE_DIR, DB_PATH, EXPORT_DIR, SAMPLE_DATA_DIR — all derived from the
  file's own location, so the pipeline works from any working directory.

SEARCH TERMS
  WEATHER_HASHTAGS (22)
      Tags queried on Bluesky and Mastodon: IMD, IndianWeather, rain, rains,
      Mumbairains, Delhirains, monsoon, monsoon2026, flood, floods, flooding,
      heatwave, heatwaves, thunderstorm, cyclone, duststorm, fog, hailstorm,
      waterlogging, weatheralert, IMDWeather, rainfall.

  WEATHER_KEYWORDS (34)
      The above lowercased, plus phrases hashtags can't express: downpour,
      waterlogged, landslide, dust storm, heat wave, strong winds, gusty
      winds, orange alert, red alert, yellow alert, imd alert. Used for
      full-text matching against RSS articles.

EVENT_CATEGORY_KEYWORDS (8 rules + default)
  An ordered list of (category, [keywords]). ORDER MATTERS — first match
  wins. The order is:

      flooding      flood, flooded, waterlogging, inundat, overflow, submerged
      thunderstorm  thunderstorm, lightning, thundershower, hailstorm, hail
      cyclone       cyclone, cyclonic storm, depression intensif
      heatwave      heatwave, heat wave, scorching, extreme heat, heatstroke
      dust_storm    dust storm, duststorm, sandstorm
      fog           fog, foggy, smog, low visibility
      strong_wind   strong wind, gusty wind, high wind, squall
      rainfall      rain, rains, raining, rainfall, downpour, monsoon, drizzle
      → other       (DEFAULT_EVENT_CATEGORY, if nothing matched)

  Why "flooding" before "rainfall": a post saying "heavy rain caused
  flooding" should be categorized as flooding, the more severe and specific
  outcome. If rainfall came first it would win on the word "rain" and the
  flooding signal would be lost. Every ordering here is deliberate — the
  more specific and severe categories sit above the general ones.

BLUESKY
  BLUESKY_PUBLIC_ENDPOINT    the broken unauthenticated endpoint (fallback)
  BLUESKY_PDS_ENDPOINT       https://bsky.social — where auth happens
  BLUESKY_IDENTIFIER         handle, from .env
  BLUESKY_APP_PASSWORD       app password, from .env
  BLUESKY_SEARCH_LIMIT       50 posts per hashtag query

MASTODON
  MASTODON_INSTANCES         mastodon.social, mstdn.social
  MASTODON_TIMELINE_LIMIT    40 posts per tag per instance

RSS_FEEDS (28)
  Grouped by type:
    Weather-specific   Skymet Weather, Down To Earth (Climate),
                       Down To Earth (Natural Disasters)
    National news      Times of India (Top Stories / India / City), NDTV,
                       Hindustan Times (India / Cities), The Hindu National,
                       Indian Express (India / Cities), News18, India Today,
                       Firstpost, Scroll.in, Deccan Herald
    City & regional    TOI Mumbai / Delhi / Bangalore / Chennai / Kolkata /
                       Hyderabad, The Hindu Kerala / Tamil Nadu /
                       Andhra Pradesh / Telangana / Karnataka

  Dead feeds log one warning and are skipped, so a broad list is safe.

OPEN-METEO
  OPENMETEO_ENDPOINT        https://api.open-meteo.com/v1/forecast
  OPENMETEO_CURRENT_VARS    10 variables: temperature_2m,
                            relative_humidity_2m, apparent_temperature,
                            precipitation, rain, weather_code, cloud_cover,
                            wind_speed_10m, wind_gusts_10m, visibility
  OPENMETEO_BATCH_SIZE      50 coordinates per HTTP call
  OPENMETEO_THRESHOLDS      heatwave_temp_c      40.0
                            heavy_rain_mm         7.5
                            very_heavy_rain_mm   15.0
                            strong_wind_kmh      40.0
                            low_visibility_m   1000.0
                            (loosely aligned with IMD advisory levels)

FILTERS
  MAX_CONTENT_AGE_HOURS     168 (one week). None disables.
  REQUIRE_INDIAN_LOCATION   True. Drops anything with no resolved state.

GEOGRAPHY
  INDIAN_STATES (36)        All states and union territories.
  INDIAN_CITIES (319)       name → (state, latitude, longitude), lowercase.

  Coverage includes metros and their older names (Bombay, Calcutta, Madras,
  Bengaluru, Vizag, Trivandrum, Baroda, Mysuru), every state and UT capital,
  tier-2 and tier-3 cities, regions that appear in weather reporting (Konkan,
  Vidarbha, Marathwada, Saurashtra, Kutch, Wayanad, Sundarbans, Brahmaputra),
  and metro localities where waterlogging is actually reported (Andheri,
  Bandra, Kurla, Sion, Malad, Powai, Koramangala, Whitefield, Gachibowli,
  Dwarka, Rohini, Thane, Navi Mumbai).

  Localities map to their parent city's coordinates. That's approximate but
  far better than discarding the row.

  THIS LIST IS THE SINGLE BIGGEST LEVER on how much data survives the India
  filter. A post about a place not in this list is thrown away.

  289 of the 319 entries are unique coordinates; the other 30 are aliases
  that collapse (bombay/mumbai, vizag/visakhapatnam). Open-Meteo polls the
  289 unique points.


================================================================================
8. CONNECTORS
================================================================================

Every connector exposes exactly one required function:

    fetch(demo: bool = False) -> list[dict]

`demo=True` reads a JSON fixture from sample_data/ instead of calling the
network, so the whole pipeline can be exercised offline.

Connectors never raise on a single failure. A dead feed, an unreachable host,
a malformed record — each logs and is skipped. One broken source must never
stop a collection run.

--------------------------------------------------------------------------------
8.1  openmeteo_connector.py — MEASURED WEATHER
--------------------------------------------------------------------------------

SERVICE:  Open-Meteo (https://open-meteo.com)
ENDPOINT: https://api.open-meteo.com/v1/forecast
AUTH:     None. Free for non-commercial use.

WHY THIS SOURCE IS DIFFERENT
  Every other connector collects what people *say* about the weather. This
  one collects what the weather *is*, from a numerical weather model, for all
  289 unique city coordinates.

  That gives the project two things nothing else does:

    1. Guaranteed volume. No key, no rate-limit cliff, no dependence on what
       anyone happened to post. It returns a full result set every run and
       cannot come back empty.

    2. Ground truth for verification. A social claim of flooding in Jaipur,
       joined against measured precipitation of 0.0mm in Jaipur at the same
       time, is a misinformation signal derived from a table join rather than
       guesswork. This is what makes verification tractable.

HOW IT WORKS

  fetch()
    1. Builds (name, state, lat, lon) for every entry in INDIAN_CITIES.
    2. De-duplicates by coordinates rounded to 4 decimal places — aliases
       like bombay/mumbai share a point and would otherwise be fetched twice.
       319 names collapse to 289 unique locations.
    3. Splits into batches of 50 and calls _fetch_batch_live per batch.
       Open-Meteo accepts comma-separated latitude/longitude lists, so all
       289 cities take 6 HTTP calls rather than 289.
    4. Converts each result block via _to_raw.

  _fetch_batch_live(cities)
    GET with params:
      latitude   = "19.076,28.7041,12.9716,..."
      longitude  = "72.8777,77.1025,77.5946,..."
      current    = the 10 variables from OPENMETEO_CURRENT_VARS
      timezone   = "Asia/Kolkata"
    A single-location request returns a dict, multi-location returns a list;
    the function normalizes that to always be a list.

  _classify(current) -> (category, human_summary)
    Derives the weather event from MEASURED VALUES, not from words.

    Threshold checks run FIRST, most severe first:
        precipitation >= 15.0mm   → flooding      "very heavy rainfall"
        precipitation >=  7.5mm   → rainfall      "heavy rainfall"
        temperature   >= 40.0°C   → heatwave      "extreme heat"
        gusts/wind    >= 40 km/h  → strong_wind   "strong winds"
        visibility    <= 1000m    → fog           "low visibility"

    Only if no threshold is breached does it fall back to the WMO weather
    interpretation code lookup (WMO_CODES, 28 entries):
        0-3    clear → overcast          → other
        45,48  fog                       → fog
        51-57  drizzle                   → rainfall
        61-67  rain                      → rainfall
        71-77  snow                      → other
        80,81  rain showers              → rainfall
        82     violent rain showers      → flooding
        95-99  thunderstorm (± hail)     → thunderstorm

    Why thresholds before codes: a measured 45 km/h gust or 42°C reading is
    more specific than the model's general "partly cloudy" code.

  _to_raw(...)
    Builds a readable English sentence from the numbers, e.g.
      "Observed conditions in Chennai, Tamil Nadu: thunderstorm.
       Temperature 30.2 C, humidity 74%, precipitation 2.1 mm,
       wind 22.8 km/h (gusts 38.4 km/h)."

    This is deliberate. Writing it as prose means the same text-based
    tooling — search, the dashboard, the ML text pipeline — works on these
    rows unchanged, instead of needing a special case.

    Sets:
      source_post_id       f"{city}-{observed_at}" — stable per city per
                           15-minute model interval, so re-running inside the
                           same interval de-duplicates instead of piling up
      verification_status  "verified" — these are measurements, not claims
      event_category       the derived category, so cleaning doesn't re-guess
                           it from the sentence
      extra                the full measured dict plus units

--------------------------------------------------------------------------------
8.2  mastodon_connector.py — PUBLIC HASHTAG TIMELINES
--------------------------------------------------------------------------------

SERVICE:  Mastodon (federated, per-instance)
ENDPOINT: https://{instance}/api/v1/timelines/tag/{hashtag}
AUTH:     None. This is the same public endpoint the instance's own
          "#hashtag" web page uses.
DOCS:     https://docs.joinmastodon.org/methods/timelines/#tag

HOW IT WORKS
  Loops over MASTODON_INSTANCES × WEATHER_HASHTAGS = 2 × 22 = 44 requests
  per run, each returning up to 40 statuses.

  Mastodon is federated — no single instance sees everything — so querying
  several large instances is how you get reach.

  _strip_html(html)
    Mastodon returns post content as HTML (`<p>Heavy rain...</p>`). This
    strips tags with a regex. Deliberately simple: we only need the text, and
    pulling in an HTML parser for this would be disproportionate.

  _status_to_raw(status)
    Maps: id → source_post_id, url → source_url, account.acct → author,
    content (stripped) → text_raw, created_at → posted_at,
    media_attachments[].url → media_urls, language → language.

  Deduplicates by (instance, status id) within a run, since the same post can
  federate to both instances.

  A defensive User-Agent header is sent — some instances and the CDNs in
  front of them reject generic clients.

--------------------------------------------------------------------------------
8.3  rss_connector.py — NEWS AND WEATHER FEEDS
--------------------------------------------------------------------------------

SERVICE:  28 Indian news and weather RSS feeds
AUTH:     None
LIBRARY:  feedparser

HOW IT WORKS
  Iterates RSS_FEEDS, parses each with feedparser.parse(url), and keeps only
  entries whose title+summary contains at least one WEATHER_KEYWORDS term.
  That filter matters — most of these are general news feeds, so the majority
  of entries are politics and sport.

  _matches_weather_keywords(text)
    Simple lowercase substring test against the 34-term keyword list.

  _entry_to_raw(entry, feed_name)
    THE IMPORTANT PART IS DATE HANDLING.

    feedparser exposes both:
      entry.published          raw RFC-2822 string, e.g.
                               "Sat, 23 Aug 2025 05:00:00 +0530"
      entry.published_parsed   a pre-parsed time.struct_time

    The connector prefers `published_parsed`, converts it with
    calendar.timegm() to a UTC epoch, then to an ISO-8601 string. Only if
    that's missing does it fall back to the raw string.

    WHY THIS MATTERS: RSS emits RFC-2822; APIs emit ISO-8601. An ISO-only
    parser silently returns None for every RSS row. Combined with the rule
    that undated records are kept rather than dropped, that let articles up
    to 400 days old walk straight past the age filter — reported as success.
    This was a real bug, found and fixed. Converting to ISO here means every
    row in the database carries one consistent format.

  Sets author to the feed name (e.g. "Skymet Weather") since an outlet, not a
  person, is the publisher.

--------------------------------------------------------------------------------
8.4  bluesky_connector.py — AUTHENTICATED HASHTAG SEARCH
--------------------------------------------------------------------------------

SERVICE:  Bluesky (AT Protocol)
AUTH:     Required — handle + app password from .env
DOCS:     https://docs.bsky.app

THE UPSTREAM PROBLEM
  Bluesky's public search endpoint

      https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts

  returns 403 Forbidden for EVERY unauthenticated query, despite their own
  documentation saying it needs no auth. This is a confirmed, unresolved bug:

      https://github.com/bluesky-social/bsky-docs/issues/332

  Adding a browser-like User-Agent does not fix it. The endpoint is simply
  closed to unauthenticated callers right now.

THE WORKAROUND
  Bluesky routes app.bsky.* calls through the user's PDS. So the connector:

    1. POSTs to https://bsky.social/xrpc/com.atproto.server.createSession
       with {identifier, password}, receiving an accessJwt.
    2. GETs https://bsky.social/xrpc/app.bsky.feed.searchPosts with
       Authorization: Bearer <accessJwt>.

  APP PASSWORDS, NOT ACCOUNT PASSWORDS
    BLUESKY_APP_PASSWORD must be an app password generated at
    Settings → Privacy and Security → App Passwords. App passwords are
    revocable, cannot change the account email, and cannot delete the
    account. If one leaks you revoke it and nothing else is affected.

FUNCTIONS
  credentials_present()   both env vars set?
  _login(attempts=3)      exchanges credentials for a token. 60s timeout,
                          retries on Timeout/ConnectionError with 5s then 10s
                          backoff — bsky.social is frequently slow and a
                          single attempt fails often enough to matter.
                          Raises a clear message on 401 explaining the
                          app-password distinction.
  _search_authenticated() searches with the Bearer token. On a 401 mid-run
                          (token expired) it re-logs-in once and retries.
  _search_public()        the broken unauthenticated path, kept as a fallback
                          so the connector starts working again on its own if
                          Bluesky ever fixes the bug.
  _search_live()          picks authenticated if credentials exist, else public.
  _post_to_raw(post)      AT-URI → source_post_id; reconstructs the permalink
                          as https://bsky.app/profile/{handle}/post/{rkey};
                          pulls embed images.
  fetch()                 logs in ONCE per run (not once per hashtag — 22
                          logins would be slow and rate-limit-prone), caches
                          the token in a module global, then searches each
                          hashtag. Suppresses repeated identical errors after
                          the second one and prints a summary count instead.

--------------------------------------------------------------------------------
8.5  citizen_connector.py — USER-SUBMITTED REPORTS
--------------------------------------------------------------------------------

SERVICE:  None — this is your own intake
STORAGE:  sample_data/citizen_reports_queue.json

  In production a mobile or web form would POST directly into the pipeline.
  Here that intake is simulated as a local JSON queue.

  submit_citizen_report(text, city, latitude, longitude, media_urls,
                        reporter_name)
      This is the function a Flask or FastAPI endpoint would call. It appends
      a record with a uuid4 id and a UTC timestamp to the queue file.

  fetch(demo) reads the queue and converts each entry.

  The point is that citizen reports flow through the SAME cleaning and
  storage path as every other source — no special casing anywhere
  downstream.


================================================================================
9. cleaning.py — NORMALIZATION AND ENRICHMENT
================================================================================

Takes a connector's raw record and produces the final 23-field row. Does NOT
do fake detection or semantic dedup — those belong to the ML stage.

REGEXES
  URL_RE        https?://\S+|www\.\S+
  HASHTAG_RE    #(\w+)
  MENTION_RE    @\w+
  WHITESPACE_RE \s+
  NON_ALNUM_RE  [^a-z0-9\s]

TIMESTAMP HANDLING

  parse_timestamp(value)
      Handles TWO standards, and getting this wrong is a real trap:
        ISO-8601   from APIs (Mastodon, Bluesky, Open-Meteo, citizen)
        RFC-2822   from RSS/Atom feeds
      Tries datetime.fromisoformat first (with Z → +00:00 substitution),
      then email.utils.parsedate_to_datetime. Naive results are assumed UTC.
      Returns None only if genuinely unparseable.

  is_too_old(posted_at)
      True if older than MAX_CONTENT_AGE_HOURS (168 = one week).

      UNPARSEABLE TIMESTAMPS ARE KEPT, NOT DROPPED. An unparseable date is a
      bug on our side, not evidence the row is worthless — dropping it would
      hide the bug and lose real data. The pipeline counts these separately
      (no_date=N) so the problem is visible rather than silent.

TEXT PROCESSING

  extract_hashtags(text)   lowercased, de-duplicated, sorted
  clean_text(text)         strips URLs and @mentions, collapses whitespace.
                           KEEPS hashtags inline, because the ML stage may
                           want the sentence context intact.

EVENT CATEGORIZATION

  guess_event_category(text)
      Walks EVENT_CATEGORY_KEYWORDS in order, returns the first match,
      defaults to "other". Ordering is severity/specificity-based (see
      section 7).

      A connector may pass `event_category` explicitly to bypass this —
      Open-Meteo does, because measurement beats keyword matching.

LOCATION RESOLUTION — the most intricate part

  AMBIGUOUS_PLACES (16 entries)
      gaya, mandi, salem, sagar, hassan, pali, puri, kota, daman, diu, leh,
      vasco, satara, bastar, goa, mathura

      These are real Indian places whose names are also common Hindi words,
      personal names, or foreign cities. Naive matching produces real errors:

          "wo chala gaya tha barish me"   → Gaya, Bihar  (Hindi for "went")
          "vegetables at the mandi"       → Mandi, HP    (Hindi for "market")
          "Salem Oregon flooding update"  → Salem, Tamil Nadu (wrong continent)

  INDIA_SIGNALS
      ("india", "indian", "imd", "bharat", "monsoon") — words that
      independently establish an Indian context.

  _has_india_signal(lowered)
      True if the text contains an INDIA_SIGNALS term, OR any UNAMBIGUOUS
      city name, OR any state name. Used to decide whether an ambiguous match
      can be trusted.

  guess_location(text, explicit_location)
      1. Builds candidates: explicit_location first (a profile location or
         place tag is more reliable than free text), then the text itself.
      2. For each candidate, scans all 319 place names with word-boundary
         regex matching — so "pune" cannot match inside another word.
      3. Splits hits into `confident` and `ambiguous`.
      4. If any confident hit: takes the LONGEST match. This is why
         "Navi Mumbai" beats "Mumbai" and "Greater Noida" beats "Noida".
      5. If ONLY ambiguous hits: requires _has_india_signal to be true.
         So "Salem Oregon" is dropped but "Salem records 80mm, Tamil Nadu on
         alert" resolves correctly.
      6. Falls back to matching a state name directly (city stays None).
      7. Returns (city, state, lat, lon, location_raw).

      Tested against 15 cases covering all these paths — all correct.

DEDUPLICATION FINGERPRINT

  make_dedup_hash(text, city, posted_at)
      Normalizes aggressively before hashing: lowercase, strip URLs, strip
      hashtags, strip all non-alphanumerics, collapse whitespace. Then
      SHA-256 of "{normalized}|{city}|{date}" where date is day-level.

      Aggressive normalization means near-identical repostings still collide.
      The day-level bucket means the same claim posted at 09:00 and 14:00
      collides, but the same claim a week later doesn't.

      This is deliberately simple. Semantic dedup — catching paraphrases —
      is the ML stage's job.

normalize_record(raw)
      Ties it together and returns the 23-field dict. Notable defaults:
        posted_at            falls back to now if the source gave nothing
        verification_status  raw's value, else "unverified"
        event_category_guess raw's value, else keyword-guessed
        is_likely_duplicate  0, set later by db.insert_record


================================================================================
10. db.py — STORAGE
================================================================================

  get_conn(db_path)      @contextmanager. Sets row_factory = sqlite3.Row so
                         rows behave like dicts. Commits on clean exit,
                         always closes.

  _table_exists(conn)    Does weather_reports exist yet?

  _migrate(conn)         Adds columns introduced after the original schema to
                         databases that already exist. SQLite's ALTER TABLE
                         ADD COLUMN backfills every existing row with the
                         column DEFAULT, so old rows get ml_label = 0 without
                         a rebuild and without touching their other fields.
                         Driven by the MIGRATIONS list. Idempotent.

  init_db(db_path)       Migrates first IF the table already exists, then runs
                         SCHEMA. That order matters: SCHEMA creates indexes
                         that reference newer columns, which would fail
                         against an un-migrated table. On a fresh database
                         there is no table, migration is skipped, and SCHEMA
                         builds everything in one go. Idempotent.

  _dedup_hash_exists()   SELECT 1 ... LIMIT 1 on the indexed dedup_hash.

  insert_record(record)  The core write. Returns one of three strings:

      'inserted'           new row written
      'duplicate_source'   (source, source_post_id) already present; the
                           UNIQUE constraint plus INSERT OR IGNORE means
                           nothing was written and nothing was overwritten
      'flagged_duplicate'  written, but is_likely_duplicate = 1 because the
                           dedup_hash matched an existing row

      Note the distinction. An exact re-fetch is SKIPPED. A near-identical
      item from a DIFFERENT source is INSERTED AND FLAGGED, not dropped —
      the ML stage may want to know a claim appeared in two places, which is
      itself a signal.

      raw_json is JSON-serialized here if it's still a dict.

  count_records()        total rows
  fetch_all()            every row as dicts, newest first
  summary_by_source()    per-source counts and duplicate totals


================================================================================
11. pipeline.py — ORCHESTRATION
================================================================================

  CONNECTORS         name → module mapping (5 entries)
  DEFAULT_SOURCES    ["openmeteo", "mastodon", "rss", "bluesky", "citizen"]

  run_pipeline(sources=None, demo=False, db_path=None)

    For each source:
      1. connector.fetch(demo) inside try/except — a crashed connector logs
         and the loop continues to the next source.
      2. For each raw record:
           normalize_record()
           skip if text_clean is empty
           count no_date if the timestamp is unparseable
           skip if is_too_old            → too_old++
           skip if no state and REQUIRE_INDIAN_LOCATION → no_location++
           db.insert_record()            → inserted / duplicate_source /
                                           flagged_duplicate ++
      3. Print a summary line.

    Returns a per-source stats dict.

  The console line looks like:

    [pipeline] rss: fetched=61 inserted=1 flagged_duplicate=0
               duplicate_source=60 too_old=0 no_location=12 no_date=0 (43.5s)

  Every record is accounted for. Nothing is dropped without a counter.


================================================================================
12. main.py — COMMAND LINE INTERFACE
================================================================================

  init-db                     Create the database and indexes.

  fetch [--source a,b] [--demo]
                              Run the pipeline. --source restricts to named
                              connectors; --demo uses fixtures.

  stats                       Row counts and duplicate counts per source.

  purge-demo [--dry-run]      Remove sample fixtures written by --demo.
                              Identifies them by reading the actual fixture
                              files and matching exact (source, id) pairs —
                              so it can ONLY ever delete known-fake rows and
                              can never touch real data.

  purge-old [--hours N] [--dry-run]
                              Delete rows older than the cutoff. Reports
                              undated rows separately and never deletes them,
                              since an unparseable date is a parsing bug, not
                              proof the row is worthless.

  purge-unlocated [--dry-run] Delete rows with no resolved Indian state.
                              Shows per-source counts and percentages plus a
                              sample of what would go.

  export --format csv|json [--out PATH]
                              Full dump for handoff.

  ALL THREE PURGE COMMANDS SUPPORT --dry-run and print what they would delete
  before you commit to it. The filters in the pipeline only apply at INSERT
  time; these commands bring existing rows in line after a config change.


================================================================================
13. scheduler.py — CONTINUOUS COLLECTION
================================================================================

  Runs two independent schedules in one process:

    FAST  mastodon, rss, bluesky, citizen    every 15 minutes
    SLOW  openmeteo                          every 60 minutes

  WHY TWO SCHEDULES
    Open-Meteo's ID is city-timestamp and its model advances every 15
    minutes, so polling it every 15 minutes yields ~289 genuinely new rows
    each time — roughly 27,000 a day. That drowns the social and news
    records (a few hundred at most) and leaves the database ~98% one source,
    which is a brutal class imbalance for any classifier.

    Hourly still gives a proper time series at a quarter the bulk. Meanwhile
    news breaks at news pace, so 15 minutes for the rest catches things
    quickly.

  FEATURES
    - Logs to console AND scheduler.log, so an overnight run can be reviewed
      afterwards.
    - Per-run summary: "+3 new (saw 61, 58 already had, 0 too old,
      12 not India) -> 1847 total"
    - run_batch never raises — a failed run logs and the loop continues.
    - SIGINT/SIGTERM handled for clean shutdown with a session summary.
    - Sleeps in short slices so Ctrl+C responds within seconds.
    - SLEEP DETECTION: if the wall clock jumps more than 3 hours (laptop
      suspended), it resets the schedule and resumes from now rather than
      firing every missed interval at once.


================================================================================
14. query_examples.py — READING THE DATA
================================================================================

  Read-only. Prints six views:
    1. Rows per source, with duplicate and verified counts
    2. Event category distribution
    3. Top 15 states
    4. Date range actually covered
    5. A filtered query — the exact shape the dashboard needs
    6. Measured (openmeteo) vs claimed rows for the same city

  The last one demonstrates the verification concept concretely.


================================================================================
15. THE THREE FILTERS
================================================================================

  FILTER            SETTING                          COUNTER      BEHAVIOUR
  ────────────────  ───────────────────────────────  ───────────  ──────────
  Age               MAX_CONTENT_AGE_HOURS = 168      too_old      dropped
  Geography         REQUIRE_INDIAN_LOCATION = True   no_location  dropped
  Unparseable date  (none — reported only)           no_date      KEPT

  WHY THE AGE FILTER
    Hashtag timelines and RSS feeds happily return content from weeks ago.
    For a real-time platform that is noise, and it silently poisons ML
    training data with stale events.

  WHY THE INDIA FILTER
    Hashtag timelines are global. A search for #rain returns Manchester and
    Melbourne alongside Mumbai. On a national platform those rows corrupt the
    dashboard's location filters and give the ML stage irrelevant examples.

    THE TRADE-OFF IS REAL: a genuinely Indian post naming no place
    ("heavy rain here since morning") is indistinguishable from a foreign one
    and gets dropped too. The fix for lost rows is widening INDIAN_CITIES,
    not disabling the filter.

  WHY UNPARSEABLE DATES ARE KEPT
    Losing real data to a parsing bug on our side is worse than admitting one
    questionable row. The counter makes it visible. A high no_date for one
    source means that source's date format needs handling — which is exactly
    how the RSS RFC-2822 bug was found.

  FILTERS ONLY APPLY TO NEW ROWS. Existing rows are untouched. After changing
  a setting, run the matching purge command.


================================================================================
16. HOW DEDUPLICATION WORKS
================================================================================

  Two layers, doing different jobs.

  LAYER 1 — EXACT, AT THE DATABASE LEVEL
    UNIQUE(source, source_post_id) + INSERT OR IGNORE.
    The same item from the same source physically cannot exist twice.
    Re-running fetch is therefore free and safe: nothing is written,
    nothing is overwritten. Reported as duplicate_source.

  LAYER 2 — NEAR-DUPLICATE, VIA FINGERPRINT
    dedup_hash = SHA-256 of aggressively normalized text + city + date.
    If a new record's hash matches an existing row, it is STILL INSERTED but
    flagged is_likely_duplicate = 1.

    Why insert rather than drop: the same claim appearing on two platforms is
    information. Amplification patterns matter for misinformation analysis.
    Dropping it would destroy that signal.

  WHAT THIS DOES NOT CATCH
    Paraphrases. "Heavy flooding in Chennai" and "Chennai streets under
    water" are semantically identical but hash differently. Catching those
    needs sentence embeddings and cosine similarity — the ML stage's job.


================================================================================
17. EVERY EXTERNAL SERVICE CALLED
================================================================================

  SERVICE        ENDPOINT                                          AUTH
  ─────────────  ────────────────────────────────────────────────  ─────────
  Open-Meteo     api.open-meteo.com/v1/forecast                    none
  Mastodon       {instance}/api/v1/timelines/tag/{tag}             none
  Bluesky auth   bsky.social/xrpc/com.atproto.server.createSession app password
  Bluesky search bsky.social/xrpc/app.bsky.feed.searchPosts        Bearer token
  RSS feeds      28 URLs (see RSS_FEEDS)                           none

  NEWS AND WEATHER DOMAINS POLLED
    skymetweather.com, downtoearth.org.in, timesofindia.indiatimes.com,
    feeds.feedburner.com (NDTV), hindustantimes.com, thehindu.com,
    indianexpress.com, news18.com, indiatoday.in, firstpost.com,
    scroll.in, deccanherald.com

  RATE LIMITING AND POLITENESS
    - Open-Meteo batches 50 coordinates per call — 6 calls, not 289.
    - Bluesky logs in once per run, not once per hashtag.
    - All HTTP calls send a descriptive User-Agent.
    - Timeouts everywhere: 15-30s reads, 60s for Bluesky login.
    - Bluesky login retries with 5s then 10s backoff.
    - Every request is wrapped so a failure logs and is skipped.


================================================================================
18. SOURCES EVALUATED AND REJECTED
================================================================================

  Each was attempted and blocked by the platform. Documented so nobody
  re-litigates them.

  REDDIT
    Closed self-serve app creation for its Data API. New apps require a
    manually reviewed request gated on moderation use cases, which an
    analytics pipeline does not qualify for. The unauthenticated .json
    endpoints were also closed in 2026 — that was the loophole around the
    paid tier, and it is gone.

  TELEGRAM
    my.telegram.org returns a bare "ERROR" on app creation with no
    explanation. Widespread and unresolved; Telegram closed the tracking
    issue as "not planned":
      https://github.com/tdlib/telegram-bot-api/issues/597
    No reliable workaround exists. A Telethon-based connector was written and
    then removed once credentials proved unobtainable.

  TWITTER / X
    No usable free read or search tier. Paid plans start around $200/month,
    and scraping violates their terms.

  DATA.GOV.IN
    Wrong shape. Its rainfall datasets are historical aggregates by
    subdivision (monthly, annual), not real-time reports. Useful later for
    computing "is today unusual for this district" baselines, but it adds no
    rows to a live feed.

  OPENWEATHERMAP / WEATHERAPI.COM
    Both require API keys to duplicate what Open-Meteo already provides
    keylessly. Redundant.


================================================================================
19. KNOWN LIMITATIONS
================================================================================

  TIMESTAMP INCONSISTENCY
    Open-Meteo timestamps are IST with no timezone marker
    ("2026-08-23T15:30"); every other source is UTC with an explicit offset.
    SQLite tolerates this because it stores text. PostgreSQL will not — a
    naive timestamp in a TIMESTAMPTZ column is interpreted in the server's
    timezone, shifting every Open-Meteo reading by 5.5 hours. THIS MUST BE
    FIXED BEFORE MIGRATING TO POSTGRES, and it also breaks any join between
    claims and measurements.

  LOCATION DETECTION IS KEYWORD MATCHING
    No geocoding, no NER. A place not in INDIAN_CITIES is invisible.
    Localities inherit their parent city's coordinates, so mapping is
    city-accurate, not street-accurate.

  OPEN-METEO IS A MODEL, NOT A RAIN GAUGE
    City-resolution numerical output, not a station reading. A genuine
    cloudburst over one neighbourhood can be real while the city figure stays
    modest. "Measured 0.0mm" is evidence against a claim, not proof it is
    false.

  event_category_guess IS A FIRST PASS
    Keyword matching (except Open-Meteo rows, derived from measurements).
    It exists so the dashboard has something to show immediately and so the
    ML stage isn't starting from zero. It is not a classifier.

  NO FAKE-REPORT TRAINING DATA
    Every source is authoritative or edited. There are essentially no
    misinformation examples in the database, so a supervised fake-detector
    has nothing to learn from. Options are fact-checker APIs (real labels,
    low volume), synthetic generation (unlimited, artificial), or
    Open-Meteo mismatch labelling (weak labels from existing data).

  POLLING, NOT STREAMING
    Each fetch is a snapshot. Bluesky and Mastodon do offer real streaming
    APIs; RSS and Open-Meteo are pull-only by nature.

  SQLITE CONCURRENCY
    Fine for one writer. A streaming collector plus a backend API reading
    simultaneously would hit lock contention. That is the argument for
    PostgreSQL.


================================================================================
20. HOW TO EXTEND IT
================================================================================

  NEW HASHTAG OR KEYWORD
    Add to WEATHER_HASHTAGS / WEATHER_KEYWORDS in config.py.

  NEW CITY
    Add "name": ("State", lat, lon) to INDIAN_CITIES. Lowercase key.
    Open-Meteo automatically starts polling it.
    If the name doubles as a common word or foreign city, ALSO add it to
    AMBIGUOUS_PLACES in cleaning.py.

  NEW RSS FEED
    Append {"name": ..., "url": ...} to RSS_FEEDS. Dead feeds are skipped
    with one warning, so a broad list is safe.

  NEW EVENT CATEGORY
    Add a (category, [keywords]) tuple to EVENT_CATEGORY_KEYWORDS. MIND THE
    ORDER — more specific and severe categories go higher.

  NEW SOURCE
    1. Create connectors/<name>_connector.py with fetch(demo=False)
       returning the raw-record shape from connectors/__init__.py.
    2. Register it in pipeline.py's CONNECTORS dict.
    3. Add it to DEFAULT_SOURCES.
    4. Add a fixture at sample_data/<name>_sample.json for --demo.
    5. If it needs credentials, read them in config.py from os.environ and
       document them in .env.example.

  CITIZEN REPORT FORM
    Point a Flask or FastAPI endpoint at
    connectors.citizen_connector.submit_citizen_report().

  MIGRATING TO POSTGRES
    1. Fix the Open-Meteo timestamp first (see section 19).
    2. Swap sqlite3.connect for psycopg2/asyncpg in db.py.
    3. INTEGER PRIMARY KEY AUTOINCREMENT → GENERATED ALWAYS AS IDENTITY.
    4. raw_json TEXT → JSONB (queryable, and it's the largest column).
    5. is_likely_duplicate INTEGER → BOOLEAN, or keep as int consistently.
    6. UNIQUE(source, source_post_id) carries over unchanged — this is what
       keeps deduplication working.
    Column names and the general shape carry over untouched. That is the
    point of keeping the schema flat.


================================================================================
END
================================================================================
