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
    raw_json                  TEXT     full original API payload (JSON string),
                                     kept so nothing is lost even if our
                                     normalization missed a useful field
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
    raw_json              TEXT,
    UNIQUE(source, source_post_id)
);
CREATE INDEX IF NOT EXISTS idx_reports_posted_at ON weather_reports(posted_at);
CREATE INDEX IF NOT EXISTS idx_reports_city ON weather_reports(city);
CREATE INDEX IF NOT EXISTS idx_reports_event_category ON weather_reports(event_category_guess);
CREATE INDEX IF NOT EXISTS idx_reports_dedup_hash ON weather_reports(dedup_hash);
"""


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH):
    with get_conn(db_path) as conn:
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
