"""
db.py
-----
SQLite storage layer. One flat table, `weather_reports`, holding every
cleaned/normalized record regardless of which source it came from. SQLite
was chosen deliberately for the hackathon hand-off: it's a single file
(weather_reports.db) you can copy, email, or `git add` - no server to spin
up. Swapping this for Postgres later is a small change (see the note at
the bottom of this file).

Columns (the "simple format" mentioned to the user) - also documented in
README.md:

    id                   INTEGER  internal auto-increment primary key
    source               TEXT     e.g. 'openmeteo', 'mastodon', 'rss', 'bluesky', 'citizen'
    source_post_id       TEXT     ID of the post on its native platform
    source_url           TEXT     permalink back to the original post
    author               TEXT     username/handle (as public as the platform exposes)
    text_raw             TEXT     original text, untouched
    text_clean           TEXT     URLs/mentions stripped, whitespace normalized
    hashtags             TEXT     comma-separated hashtags found in the text
    posted_at            TEXT     ISO-8601 timestamp the post was made
    ingested_at          TEXT     ISO-8601 timestamp we pulled it into this DB
    city                 TEXT     best-guess Indian city (nullable)
    state                TEXT     best-guess Indian state (nullable)
    latitude              REAL     best-guess latitude (nullable)
    longitude             REAL     best-guess longitude (nullable)
    location_raw          TEXT     the raw text we extracted location from
    media_urls            TEXT     comma-separated photo/video URLs
    media_type             TEXT     'photo' | 'video' | 'none'
    event_category_guess   TEXT     rule-based guess (rainfall/flooding/etc) - NOT final
    language                TEXT     language code if the source provides one
    dedup_hash              TEXT     fingerprint for cheap duplicate detection
    is_likely_duplicate      INTEGER 0/1 - set true if dedup_hash collided with
                                     an existing row already in the DB
    verification_status      TEXT     'unverified' | 'verified' | 'fake' - the ML
                                     teammate / admin panel updates this later
    ml_label                  INTEGER 0 = genuine, 1 = fabricated. THE SUPERVISED
                                     TRAINING TARGET. See the note below.
    raw_json                  TEXT     full original API payload (JSON string),
                                     kept so nothing is lost even if our
                                     normalization missed a useful field


ml_label VS verification_status - THEY ARE NOT THE SAME THING
-------------------------------------------------------------
verification_status records PROVENANCE and workflow state: where a row came
from, and whether a human or the admin panel has ruled on it. 'verified' on
an Open-Meteo row means "this is a measurement", not "this claim was checked
and held up".

ml_label is the SUPERVISED TARGET: is this text fabricated or not.

    0 = genuine       collected from a real source
    1 = fabricated    deliberately synthesized as a training negative

Everything collected by this pipeline is 0, because we collected it from real
services. Class 1 rows come from a separate generator, not from here.

Training on verification_status instead would be label leakage - the model
would just learn to recognise Open-Meteo's sentence template and score ~99%
while detecting nothing.

HONEST CAVEAT: ml_label=0 means "we did not fabricate this", not "this claim
is true". A collected social post could still be misinformation nobody has
checked. Open-Meteo and RSS rows are safe to treat as genuine; social rows
are presumed-genuine-but-unverified. That distinction lives in
verification_status, which is why both columns exist.
"""

import json
import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_reports (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source                TEXT NOT NULL,
    source_post_id        TEXT,
    source_url            TEXT,
    author                TEXT,
    text_raw              TEXT,
    text_clean            TEXT,
    hashtags              TEXT,
    posted_at             TEXT,
    ingested_at           TEXT,
    city                  TEXT,
    state                 TEXT,
    latitude              REAL,
    longitude             REAL,
    location_raw          TEXT,
    media_urls            TEXT,
    media_type            TEXT,
    event_category_guess  TEXT,
    language              TEXT,
    dedup_hash            TEXT,
    is_likely_duplicate   INTEGER DEFAULT 0,
    verification_status   TEXT DEFAULT 'unverified',
    ml_label              INTEGER DEFAULT 0,
    raw_json              TEXT,
    UNIQUE(source, source_post_id)
);
CREATE INDEX IF NOT EXISTS idx_reports_posted_at ON weather_reports(posted_at);
CREATE INDEX IF NOT EXISTS idx_reports_city ON weather_reports(city);
CREATE INDEX IF NOT EXISTS idx_reports_event_category ON weather_reports(event_category_guess);
CREATE INDEX IF NOT EXISTS idx_reports_dedup_hash ON weather_reports(dedup_hash);
CREATE INDEX IF NOT EXISTS idx_reports_ml_label ON weather_reports(ml_label);
"""

# Columns added after the original schema shipped. Existing databases get them
# via ALTER TABLE rather than needing a rebuild - see _migrate().
#   (column name, SQL type + default)
MIGRATIONS = [
    ("ml_label", "INTEGER DEFAULT 0"),
]


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _table_exists(conn) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='weather_reports'"
    ).fetchone() is not None


def _migrate(conn):
    """
    Add any columns introduced after the original schema, to databases that
    already exist. SQLite's ALTER TABLE ADD COLUMN backfills every existing
    row with the column's DEFAULT, so old rows get ml_label = 0 automatically
    without a rebuild and without touching any of their other fields.

    Idempotent - checks what's already there before altering.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(weather_reports)")}
    for column, spec in MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE weather_reports ADD COLUMN {column} {spec}")
            print(f"[db] migrated: added column '{column}' ({spec}) - "
                  f"existing rows backfilled with the default")


def init_db(db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        # Order matters. If the table already exists, migrate it BEFORE running
        # SCHEMA - SCHEMA creates indexes that may reference newly added
        # columns, and those would fail against an un-migrated table.
        # On a fresh database there's no table yet, so migration is skipped and
        # SCHEMA creates everything correctly in one go.
        if _table_exists(conn):
            _migrate(conn)
        conn.executescript(SCHEMA)


def _dedup_hash_exists(conn, dedup_hash: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM weather_reports WHERE dedup_hash = ? LIMIT 1", (dedup_hash,)
    )
    return cur.fetchone() is not None


def insert_record(record: dict, db_path: str = DB_PATH) -> str:
    """
    Insert one normalized record. Returns one of:
        'inserted'          new row written
        'duplicate_source'  same (source, source_post_id) already present -> skipped
        'flagged_duplicate' new row written, but flagged is_likely_duplicate=1
                             because its dedup_hash matches an existing row
                             (e.g. same report picked up from two platforms)
    """
    record = dict(record)  # don't mutate caller's dict
    if isinstance(record.get("raw_json"), (dict, list)):
        record["raw_json"] = json.dumps(record["raw_json"], ensure_ascii=False, default=str)

    with get_conn(db_path) as conn:
        if record.get("dedup_hash") and _dedup_hash_exists(conn, record["dedup_hash"]):
            record["is_likely_duplicate"] = 1

        columns = list(record.keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_list = ", ".join(columns)
        sql = f"INSERT OR IGNORE INTO weather_reports ({col_list}) VALUES ({placeholders})"
        cur = conn.execute(sql, [record[c] for c in columns])
        if cur.rowcount == 0:
            return "duplicate_source"
        return "flagged_duplicate" if record["is_likely_duplicate"] else "inserted"


def count_records(db_path: str = DB_PATH) -> int:
    with get_conn(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM weather_reports").fetchone()[0]


def fetch_all(db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM weather_reports ORDER BY posted_at DESC")]


def summary_by_source(db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) as n, SUM(is_likely_duplicate) as dupes "
            "FROM weather_reports GROUP BY source ORDER BY n DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Moving to Postgres later (e.g. for the real-time dashboard team):
#   1. Swap sqlite3.connect(...) for psycopg2/SQLAlchemy connect.
#   2. AUTOINCREMENT -> SERIAL / GENERATED ALWAYS AS IDENTITY.
#   3. Everything else (column names, types, indexes) carries over almost
#      unchanged - that's the point of keeping this schema flat and boring.
# ---------------------------------------------------------------------------
