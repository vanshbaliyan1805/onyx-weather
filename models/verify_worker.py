"""
verify_worker.py
----------------
Cross-references every checkable post against what the weather actually did,
and writes the verdict into the database.

    python verify_worker.py                # check everything unchecked
    python verify_worker.py --limit 50
    python verify_worker.py --dry-run      # print, write nothing
    python verify_worker.py --all          # re-check rows already checked

Runs against whichever database db.py is pointing at - Supabase, or the local
SQLite file when ONYX_LOCAL_DB is set.

Writes three columns:

    measurement_check       'agrees' | 'contradicted' | 'unverifiable'
    measurement_note        readable, e.g. "claims flooding - only 0.4mm in 24h"
    measurement_severity    0-1, how badly the claim missed. A -12C claim on a
                            26C day misses by 38 degrees and scores 1.0; a
                            "heatwave" claim on a 28.5C day barely registers.
                            The blend uses this instead of a flat 1.0, which is
                            what lets a decisive contradiction reach 'fake'
                            without the classifier having to agree.
    measurement_checked_at  when the check ran

This is the second half of the detector. The model reads the sentence and
judges how it sounds; this ignores the writing entirely and asks whether the
world agrees. A calm, plausible lie gets past the first and is caught by the
second.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verification import (fetch_history, check_claim,  # noqa: E402
                          CHECKABLE_SOURCES, AGREES,
                          CONTRADICTED, UNVERIFIABLE)

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', '.env'))

def get_conn():
    url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
    return psycopg2.connect(url)

def fetch_rows(limit, recheck_all):
    sources = "', '".join(sorted(CHECKABLE_SOURCES))
    where = [f"source IN ('{sources}')", "latitude IS NOT NULL"]
    if not recheck_all:
        where.append("measurement_check IS NULL")
    sql = f"""
        SELECT id, source, city, state, latitude, longitude,
               posted_at, event_category_guess, text_clean, author
        FROM weather_reports
        WHERE {' AND '.join(where)}
        ORDER BY posted_at DESC
        {f'LIMIT {int(limit)}' if limit else ''}
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def write_results(rows):
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    UPDATE weather_reports
                       SET measurement_check      = %s,
                           measurement_note       = %s,
                           measurement_severity   = %s,
                           measurement_checked_at = %s
                     WHERE id = %s
                    """,
                    (r["verdict"], r["note"], r.get("severity", 0.0),
                     now, r["id"]),
                )
        conn.commit()


def main():
    ap = argparse.ArgumentParser(description="Cross-reference claims against measurements")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="re-check rows already checked")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = fetch_rows(args.limit, args.all)
    if not rows:
        print("nothing to check.")
        print(f"(only {', '.join(sorted(CHECKABLE_SOURCES))} rows with a "
              f"resolved location are checkable)")
        return

    print(f"{len(rows)} rows to check")

    coords = sorted({(round(r["latitude"], 3), round(r["longitude"], 3))
                     for r in rows})
    print(f"{len(coords)} distinct locations to look up")
    history = fetch_history(coords)

    counts = {AGREES: 0, CONTRADICTED: 0, UNVERIFIABLE: 0}
    for r in rows:
        key = (round(r["latitude"], 3), round(r["longitude"], 3))
        when = r["posted_at"]
        if isinstance(when, str):
            try:
                when = datetime.fromisoformat(when.replace("Z", "+00:00"))
            except ValueError:
                when = None
        verdict, note, severity = check_claim(
            r["event_category_guess"], history.get(key), when, r["source"],
            r["text_clean"], r.get("author"), r.get("city"),
        )
        r["verdict"], r["note"], r["severity"] = verdict, note, severity
        counts[verdict] += 1

    print()
    for k in (CONTRADICTED, AGREES, UNVERIFIABLE):
        print(f"  {k:<14} {counts[k]}")

    flagged = [r for r in rows if r["verdict"] == CONTRADICTED]
    if flagged:
        print(f"\n=== CONTRADICTED BY MEASUREMENT ({len(flagged)}) ===")
        for r in flagged[:15]:
            print(f"\n  [{r['source']} / {r['city']}]  {r['note']}"
                  f"   (severity {r['severity']:.2f})")
            print(f"  {(r['text_clean'] or '')[:150]}")

    confirmed = [r for r in rows if r["verdict"] == AGREES]
    if confirmed:
        print(f"\n=== SUPPORTED BY MEASUREMENT ({len(confirmed)}) ===")
        for r in confirmed[:5]:
            print(f"  [{r['city']}]  {r['note']}")
            print(f"    {(r['text_clean'] or '')[:120]}")

    if args.dry_run:
        print("\ndry run - nothing written.")
        return

    write_results(rows)
    print(f"\nwrote {len(rows)} checks to Supabase")
    print("  (measurement_check, measurement_note, measurement_severity, "
          "measurement_checked_at)")


if __name__ == "__main__":
    main()
