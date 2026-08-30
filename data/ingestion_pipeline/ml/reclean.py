"""
reclean.py
----------
Re-runs the CURRENT cleaning rules over every row already in Supabase.

    python ml/reclean.py --dry-run     # show what would change, write nothing
    python ml/reclean.py               # apply

Why this exists
---------------
`text_clean` is written once, at insert time, by whatever version of
clean_text() was running that day. Improve the cleaner and every row
collected before the improvement keeps its old, dirtier text - and because
those rows are all from the same era and the same sources, that dirt is
correlated with the label. The leakage check found exactly this: 10.9% of
genuine rows still carried HTML artefacts against 0% of synthetic ones, which
is a free giveaway a model will find before it reads a single word.

`text_raw` is never modified by the pipeline, so it is always possible to
rebuild `text_clean` from scratch. That is the whole reason both columns
exist.

What it touches
---------------
`text_clean` and `dedup_hash` only. Nothing else - not text_raw, not any
ML column, not the timestamps. Rows whose cleaned text is already correct
are skipped entirely, so this is safe to run as often as you like.
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PIPELINE = os.path.dirname(_HERE)
if _PIPELINE not in sys.path:
    sys.path.insert(0, _PIPELINE)

import db                                          # noqa: E402
from cleaning import clean_text, make_dedup_hash   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Re-clean existing rows")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, write nothing")
    ap.add_argument("--show", type=int, default=5,
                    help="how many before/after examples to print")
    args = ap.parse_args()

    print("reading rows...")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, source, text_raw, text_clean, city, posted_at
                FROM weather_reports
                WHERE text_raw IS NOT NULL AND text_raw <> ''
                ORDER BY id
            """)
            rows = cur.fetchall()

    print(f"{len(rows)} rows to check\n")

    changes = []
    for row_id, source, text_raw, old_clean, city, posted_at in rows:
        new_clean = clean_text(text_raw)
        if not new_clean or new_clean == (old_clean or ""):
            continue
        posted_str = posted_at.isoformat() if posted_at else ""
        new_hash = make_dedup_hash(new_clean, city, posted_str)
        changes.append((row_id, source, old_clean or "", new_clean, new_hash))

    print(f"{len(changes)} rows would change "
          f"({100.0 * len(changes) / max(len(rows), 1):.1f}%)\n")

    if changes:
        by_source = {}
        for _, source, _, _, _ in changes:
            by_source[source] = by_source.get(source, 0) + 1
        print("by source:", dict(sorted(by_source.items(),
                                        key=lambda kv: -kv[1])))
        print()
        for _, source, old, new, _ in changes[:args.show]:
            print(f"--- {source} ---")
            print(f"  before: {old[:150]}")
            print(f"  after : {new[:150]}\n")

    if args.dry_run:
        print("dry run - nothing written. Drop --dry-run to apply.")
        return

    if not changes:
        print("nothing to do.")
        return

    print(f"updating {len(changes)} rows...")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for row_id, _, _, new_clean, new_hash in changes:
                cur.execute(
                    "UPDATE weather_reports "
                    "SET text_clean = %s, dedup_hash = %s WHERE id = %s",
                    (new_clean, new_hash, row_id),
                )
    print("done. Rebuild the dataset now:")
    print("  .\\.venv\\Scripts\\python.exe ml\\build_dataset.py")


if __name__ == "__main__":
    main()
