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
import psycopg2
from psycopg2.extras import DictCursor
from contextlib import contextmanager
import os
from dotenv import load_dotenv

from config import DB_PATH

# Load from backend .env for local dev
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "backend", ".env"))

# Extract database URL from env, removing +asyncpg if present so psycopg2 can use it
DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy backend/.env.example to backend/.env and "
        "fill in the connection string. No default is provided on purpose: a silent "
        "fallback to localhost turns a missing config into a confusing "
        "'connection refused' several layers deep."
    )
if DB_URL.startswith("postgresql+asyncpg://"):
    DB_URL = DB_URL.replace("postgresql+asyncpg://", "postgresql://")
@contextmanager
def get_conn(*args, **kwargs):
    conn = psycopg2.connect(DB_URL)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db(*args, **kwargs):
    # Schema creation is now handled by backend Alembic migrations.
    pass

def _dedup_hash_exists(conn, dedup_hash: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM weather_reports WHERE dedup_hash = %s LIMIT 1", (dedup_hash,)
        )
        return cur.fetchone() is not None

def insert_record(record: dict, *args, **kwargs) -> str:
    """
    Insert one normalized record. Returns one of:
        'inserted'          new row written
        'duplicate_source'  same (source, source_post_id) already present -> skipped
        'flagged_duplicate' new row written, but flagged is_likely_duplicate=1
    """
    record = dict(record)  # don't mutate caller's dict
    if isinstance(record.get("raw_json"), (dict, list)):
        record["raw_json"] = json.dumps(record["raw_json"], ensure_ascii=False, default=str)

    with get_conn() as conn:
        if record.get("dedup_hash") and _dedup_hash_exists(conn, record["dedup_hash"]):
            record["is_likely_duplicate"] = 1
        else:
            record["is_likely_duplicate"] = 0

        columns = list(record.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        col_list = ", ".join(columns)
        sql = f"""
            INSERT INTO weather_reports ({col_list}) 
            VALUES ({placeholders})
            ON CONFLICT (source, source_post_id) DO NOTHING
        """
        
        with conn.cursor() as cur:
            cur.execute(sql, [record[c] for c in columns])
            if cur.rowcount == 0:
                return "duplicate_source"
            return "flagged_duplicate" if record["is_likely_duplicate"] else "inserted"

def count_records(*args, **kwargs) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM weather_reports")
            return cur.fetchone()[0]

def fetch_all(*args, **kwargs):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM weather_reports ORDER BY posted_at DESC")
            return [dict(row) for row in cur.fetchall()]

def summary_by_source(*args, **kwargs):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("""
                SELECT source, COUNT(*) as n, SUM(is_likely_duplicate) as dupes 
                FROM weather_reports GROUP BY source ORDER BY n DESC
            """)
            return [dict(r) for r in cur.fetchall()]
