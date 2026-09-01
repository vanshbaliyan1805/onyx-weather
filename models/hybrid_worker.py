"""
hybrid_worker.py
----------------
Lightweight worker for calculating the final hybrid verdict.
It blends the previously computed fake_probability from the DistilBERT model
with measurement checks, physics rules, and source credibility.

Usage:
    python models/hybrid_worker.py --limit 200
    python models/hybrid_worker.py --all
"""

import argparse
import os
import sys
import json
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HYBRID_DIR = os.path.join(SCRIPT_DIR, "hybrid")
if HYBRID_DIR not in sys.path:
    sys.path.insert(0, HYBRID_DIR)
ENV_PATH = os.path.join(SCRIPT_DIR, "..", "backend", ".env")

def load_hybrid():
    from hybrid import hybrid_score, explain as hybrid_explain, verdict_for
    return hybrid_score, hybrid_explain, verdict_for

def get_db_url():
    load_dotenv(ENV_PATH)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print(f"Error: DATABASE_URL not set (checked {ENV_PATH})")
        sys.exit(1)
    return url.replace("postgresql+asyncpg://", "postgresql://")

def process_hybrid(limit: int, recheck_all: bool):
    hybrid_score_fn, hybrid_explain_fn, verdict_for_fn = load_hybrid()
    
    url = get_db_url()
    conn = psycopg2.connect(url)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # --------------------------------------------------------------
            # INTENTIONAL NULL BEHAVIOR:
            # When hybrid_updated_at is populated and measurement_checked_at is NULL, 
            # the comparison (hybrid_updated_at < measurement_checked_at) evaluates to NULL (falsy)
            # and the row is safely skipped. This is exactly what we want because it means
            # no measurement result has arrived yet to invalidate the current hybrid score.
            # --------------------------------------------------------------
            where_clause = "ml_status = 'completed' AND source NOT IN ('openmeteo', 'rss')"
            if not recheck_all:
                where_clause += " AND (hybrid_updated_at IS NULL OR hybrid_updated_at < measurement_checked_at)"
            
            cur.execute(f"""
                SELECT id, text_clean, event_category_guess, author, source, 
                       measurement_check, measurement_severity, fake_probability, ml_confidence
                FROM weather_reports
                WHERE {where_clause}
                ORDER BY id ASC
                {f'LIMIT {limit}' if limit else ''}
            """)
            records = cur.fetchall()

            total = len(records)
            print(f"Found: {total} record(s) requiring hybrid recomputation")
            if total == 0:
                print("Nothing to process.")
                return

            completed = 0
            failed = 0
            now = datetime.now(timezone.utc)

            for r in records:
                try:
                    # DistilBERT outputs must exist!
                    if r["fake_probability"] is None:
                        # Should not happen because ml_status = 'completed', but safety check
                        raise ValueError("fake_probability is NULL for a completed ML record")

                    # Call the hybrid module exactly as ml_worker used to
                    score, breakdown = hybrid_score_fn(
                        ml=r["fake_probability"],
                        measurement_check=r["measurement_check"],
                        text=r["text_clean"] or "",
                        author=r["author"],
                        source=r["source"],
                        severity=r["measurement_severity"]
                    )
                    verdict = breakdown.get("verdict")
                    
                    cur.execute("""
                        UPDATE weather_reports
                        SET hybrid_score = %s,
                            hybrid_signals = %s,
                            verdict = %s,
                            hybrid_updated_at = %s
                        WHERE id = %s
                    """, (score, json.dumps(breakdown), verdict, now, r["id"]))
                    
                    completed += 1
                except Exception as e:
                    print(f"Failed hybrid computation for ID {r['id']}: {e}")
                    failed += 1

            conn.commit()
            print(f"Processed {completed} successfully, {failed} failed.")

    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run hybrid signal blending")
    parser.add_argument("--limit", type=int, default=None, help="Max records to process")
    parser.add_argument("--all", action="store_true", help="Re-blend ALL completed records (Use cautiously)")
    args = parser.parse_args()

    process_hybrid(limit=args.limit, recheck_all=args.all)
