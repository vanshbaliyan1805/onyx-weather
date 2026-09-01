"""
hybrid_worker.py
----------------
Recomputes the blended score for every row and writes it back.

    python hybrid_worker.py                # rows not yet blended
    python hybrid_worker.py --all          # everything
    python hybrid_worker.py --all --dry-run

Run it after ml/score_worker.py and verify_worker.py. It reads what they
wrote, adds the two rule signals, and writes three columns:

    hybrid_score      0-1, or NULL when nothing could be evaluated
    hybrid_signals    JSON: every signal, its weight, its contribution
    verdict           fake | suspect | ok | unchecked, derived from the score

Nothing here is authored by hand. Delete all three columns and one run
rebuilds them from the evidence, which is what makes the number trustworthy:
it cannot drift from what the workers actually found.

The columns are added on first run with ALTER TABLE ... ADD COLUMN, which
both SQLite and Postgres accept, so the local database needs no migration.
For Supabase, add them to the model and generate an Alembic revision as well
so the schema file stays the source of truth.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The pipeline root, where db.py lives.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db                                             # noqa: E402
from hybrid import hybrid_score, to_json, explain      # noqa: E402

NEW_COLUMNS = [
    ("hybrid_score", "DOUBLE PRECISION"),
    ("hybrid_signals", "TEXT"),
    ("verdict", "TEXT"),
]


def ensure_columns():
    """Idempotent. SQLite and Postgres both ignore a duplicate-column error
    differently, so the exception is caught rather than probed for."""
    for name, sqltype in NEW_COLUMNS:
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"ALTER TABLE weather_reports ADD COLUMN {name} {sqltype}")
            print(f"  added column {name}")
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "exists" in str(exc).lower():
                continue
            raise


def fetch(limit, do_all):
    where = "" if do_all else "WHERE hybrid_score IS NULL"
    sql = f"""
        SELECT id, text_clean, author, source, fake_probability,
               measurement_check
        FROM weather_reports
        {where}
        ORDER BY id DESC
        LIMIT {int(limit)}
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--all", action="store_true",
                    help="rescore rows that already have a hybrid score")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", type=int, default=8,
                    help="how many flagged rows to print")
    args = ap.parse_args()

    if not args.dry_run:
        ensure_columns()

    rows = fetch(args.limit, args.all)
    print(f"{len(rows)} rows to blend\n")

    updates, counts, flagged = [], {}, []
    for rid, text, author, source, ml, mcheck in rows:
        score, breakdown = hybrid_score(
            ml=ml, measurement_check=mcheck,
            text=text, author=author, source=source)
        v = breakdown["verdict"]
        counts[v] = counts.get(v, 0) + 1
        updates.append((score, to_json(breakdown), v, rid))
        if v in ("fake", "suspect"):
            flagged.append((score, v, breakdown, text or "", source))

    flagged.sort(reverse=True, key=lambda r: r[0] or 0)

    # Collapse repeats for DISPLAY only - every row still gets its score
    # written. The same post arrives from two Mastodon instances with the
    # author spelt differently, and rows cleaned before the hashtag fix have
    # a different dedup_hash from rows cleaned after, so the same fake can
    # appear three times. Showing it three times makes the dashboard look
    # broken even though the scoring is right.
    seen, unique = set(), []
    for row in flagged:
        key = "".join(ch for ch in (row[3] or "").lower() if ch.isalnum())[:120]
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    dupes = len(flagged) - len(unique)

    if unique:
        print(f"=== FLAGGED ({len(unique)} distinct"
              + (f", {dupes} repeats hidden" if dupes else "")
              + ") - highest first ===\n")
        for score, v, bd, text, source in unique[:args.show]:
            print(f"  [{v.upper()} {score:.3f}]  driver: {bd['driver']}  "
                  f"({source})")
            print(f"  {text[:100]}")
            print(f"    {explain(bd)}")
            print()

    print("verdicts:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))

    if args.dry_run:
        print("\ndry run - nothing written")
        return

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for score, sig, v, rid in updates:
                cur.execute(
                    "UPDATE weather_reports SET hybrid_score = %s, "
                    "hybrid_signals = %s, verdict = %s WHERE id = %s",
                    (score, sig, v, rid))
    print(f"\nwrote {len(updates)} rows")


if __name__ == "__main__":
    main()
