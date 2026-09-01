"""
fix_schema.py
-------------
Adds every column the verification and hybrid workers need, to whichever
database db.py is currently pointing at.

    python hybrid\\fix_schema.py

Why this exists
---------------
The measurement columns were only ever added to the local SQLite file. The
pipeline is now writing to Supabase, where they do not exist - which is why
verify_worker.py died with

    psycopg2.errors.UndefinedColumn: column "measurement_check" of relation
    "weather_reports" does not exist

Every statement runs in its own connection, because Postgres aborts the
whole transaction when one statement fails, so a single shared connection
would take the rest of the columns down with the first duplicate.

Safe to run repeatedly. It never drops or rewrites anything.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

# Postgres types. SQLite ignores the declared type almost entirely, so the
# same DDL works on both.
COLUMNS = [
    ("measurement_check",      "TEXT"),
    ("measurement_note",       "TEXT"),
    ("measurement_checked_at", "TIMESTAMPTZ"),
    ("hybrid_score",           "DOUBLE PRECISION"),
    ("hybrid_signals",         "TEXT"),
    ("verdict",                "TEXT"),
]

INDEXES = [
    ("ix_weather_reports_verdict", "verdict"),
    ("ix_weather_reports_measurement_check", "measurement_check"),
    ("ix_weather_reports_hybrid_score", "hybrid_score"),
]


def already_there(exc) -> bool:
    m = str(exc).lower()
    return "duplicate" in m or "already exists" in m or "exists" in m


def main():
    added, present = [], []
    for name, sqltype in COLUMNS:
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"ALTER TABLE weather_reports ADD COLUMN {name} {sqltype}")
            added.append(name)
        except Exception as exc:
            if already_there(exc):
                present.append(name)
            else:
                print(f"  ! {name}: {exc}")

    for idx, col in INDEXES:
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"CREATE INDEX {idx} ON weather_reports ({col})")
        except Exception:
            pass          # already there, or the column failed above

    if added:
        print("added:   " + ", ".join(added))
    if present:
        print("already: " + ", ".join(present))
    print("\nschema is ready. now run:")
    print("  python verify_worker.py --limit 400 --all")
    print("  python hybrid\\hybrid_worker.py --all")


if __name__ == "__main__":
    main()
