"""
main.py
-------
CLI entry point.
 
Examples:
 
    # first-time setup
    python main.py init-db
 
    # demo run using bundled sample data (no API keys / internet needed)
    python main.py fetch --demo
 
    # live run, all sources
    python main.py fetch
 
    # live run, just one source
    python main.py fetch --source reddit
 
    # see what's in the DB
    python main.py stats
 
    # hand off to your ML teammate
    python main.py export --format csv --out exports/weather_reports.csv
    python main.py export --format json --out exports/weather_reports.json
"""
 
import argparse
import csv
import json
import os
 
import db
from pipeline import run_pipeline, CONNECTORS
from config import EXPORT_DIR, SAMPLE_DATA_DIR
 
 
def cmd_init_db(args):
    db.init_db()
    print(f"Database ready at {db.DB_PATH}")
 
 
def _demo_row_keys() -> list:
    """
    Build the exact (source, source_post_id) list of every record that lives
    in sample_data/. Reading the fixtures themselves - rather than guessing
    by source name or date - means this only ever deletes known-fake rows and
    can never touch real collected data.
    """
    keys = []
 
    def add(source, ids):
        keys.extend((source, str(i)) for i in ids if i)
 
    def load(filename):
        path = os.path.join(SAMPLE_DATA_DIR, filename)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
 
    add("bluesky", [p.get("uri") or p.get("cid") for p in load("bluesky_sample.json")])
    add("mastodon", [s.get("id") or s.get("uri") for s in load("mastodon_sample.json")])
    add("reddit", [i.get("id") for i in load("reddit_sample.json")])
    add("rss", [i.get("link") for i in load("rss_sample.json")])
    add("citizen", [r.get("id") for r in load("citizen_reports_sample.json")])
    add("openmeteo", [
        f"{i['city']}-{i['block']['current']['time']}"
        for i in load("openmeteo_sample.json")
        if i.get("city") and i.get("block", {}).get("current", {}).get("time")
    ])
    return keys
 
 
def cmd_purge_demo(args):
    """Remove sample/demo rows that were written by `fetch --demo`."""
    keys = _demo_row_keys()
    if not keys:
        print("No sample fixtures found - nothing to purge.")
        return
 
    with db.get_conn() as conn:
        found = []
        for source, post_id in keys:
            row = conn.execute(
                "SELECT id, source, city, text_clean FROM weather_reports "
                "WHERE source = ? AND source_post_id = ?",
                (source, post_id),
            ).fetchone()
            if row:
                found.append(dict(row))
 
        if not found:
            print("Clean - no demo rows present in the database.")
            return
 
        print(f"Found {len(found)} demo row(s):\n")
        for r in found:
            preview = (r["text_clean"] or "")[:64]
            print(f"  [{r['source']}] {r['city'] or '-'}: {preview}...")
 
        if args.dry_run:
            print("\n(dry run - nothing deleted. Re-run without --dry-run to remove them.)")
            return
 
        conn.executemany(
            "DELETE FROM weather_reports WHERE source = ? AND source_post_id = ?", keys
        )
 
    print(f"\nDeleted {len(found)} demo row(s). Remaining rows: {db.count_records()}")
 
 
def cmd_fetch(args):
    sources = args.source.split(",") if args.source else None
    if sources:
        for s in sources:
            if s not in CONNECTORS:
                raise SystemExit(f"Unknown source '{s}'. Choose from: {', '.join(CONNECTORS)}")
    run_pipeline(sources=sources, demo=args.demo)
    print(f"\nTotal rows in DB: {db.count_records()}")
 
 
def cmd_stats(args):
    total = db.count_records()
    print(f"Total rows: {total}\n")
    print(f"{'source':<10} {'rows':>6} {'flagged_dupes':>14}")
    for row in db.summary_by_source():
        print(f"{row['source']:<10} {row['n']:>6} {row['dupes'] or 0:>14}")
 
 
def cmd_export(args):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    out_path = args.out or os.path.join(
        EXPORT_DIR, f"weather_reports.{args.format}"
    )
    rows = db.fetch_all()
 
    if args.format == "json":
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    elif args.format == "csv":
        if not rows:
            print("No rows to export yet - run `fetch` first.")
            return
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        raise SystemExit(f"Unsupported format: {args.format}")
 
    print(f"Exported {len(rows)} rows to {out_path}")
 
 
def build_parser():
    parser = argparse.ArgumentParser(description="Onyx weather data ingestion pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
 
    p_init = sub.add_parser("init-db", help="Create the SQLite database and tables")
    p_init.set_defaults(func=cmd_init_db)
 
    p_fetch = sub.add_parser("fetch", help="Fetch, clean, and store weather reports")
    p_fetch.add_argument("--source", help=f"Comma-separated source(s): {', '.join(CONNECTORS)}. Default: all")
    p_fetch.add_argument("--demo", action="store_true", help="Use bundled sample data instead of live APIs")
    p_fetch.set_defaults(func=cmd_fetch)
 
    p_stats = sub.add_parser("stats", help="Show row counts by source")
    p_stats.set_defaults(func=cmd_stats)
 
    p_purge = sub.add_parser(
        "purge-demo",
        help="Delete sample/demo rows that were written into the DB by `fetch --demo`",
    )
    p_purge.add_argument("--dry-run", action="store_true", help="List what would be deleted, delete nothing")
    p_purge.set_defaults(func=cmd_purge_demo)
 
    p_export = sub.add_parser("export", help="Export the database for handoff")
    p_export.add_argument("--format", choices=["csv", "json"], default="csv")
    p_export.add_argument("--out", help="Output file path (default: exports/weather_reports.<format>)")
    p_export.set_defaults(func=cmd_export)
 
    return parser
 
 
if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)