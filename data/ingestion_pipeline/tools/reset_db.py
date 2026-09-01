"""
reset_db.py
-----------
Empties the local weather_reports table.

    python tools\\reset_db.py              # show what would go, ask, then delete
    python tools\\reset_db.py --yes        # skip the prompt
    python tools\\reset_db.py --source mastodon   # only one source
    python tools\\reset_db.py --dry-run

REFUSES TO RUN AGAINST SUPABASE. ONYX_LOCAL_DB must be set. That table is
shared with the rest of the team, an accidental wipe is not recoverable from
this side, and a delete script is exactly the kind of thing that gets run in
the wrong terminal at 2am. If you genuinely need to clear the hosted
database, do it from the Supabase SQL editor where the target is visible on
screen.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--source", help="only delete rows from this source")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    local = os.environ.get("ONYX_LOCAL_DB")
    if not local:
        sys.exit(
            "ONYX_LOCAL_DB is not set, so this would delete from Supabase.\n"
            "Refusing. Run:  $env:ONYX_LOCAL_DB = \"weather_local.db\""
        )

    import db

    where, params = "", ()
    if args.source:
        where, params = " WHERE source = %s", (args.source,)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM weather_reports" + where, params)
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT source, COUNT(*) FROM weather_reports" + where +
                " GROUP BY source ORDER BY 2 DESC", params)
            breakdown = cur.fetchall()

    print(f"database: {local}")
    print(f"rows to delete: {total}")
    for src, n in breakdown:
        print(f"  {src:<12} {n}")

    if total == 0:
        print("\nnothing to do")
        return
    if args.dry_run:
        print("\ndry run - nothing deleted")
        return

    if not args.yes:
        print(f"\nThis deletes {total} rows from {local} and cannot be undone.")
        if input("Type DELETE to confirm: ").strip() != "DELETE":
            print("cancelled")
            return

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM weather_reports" + where, params)
            # SQLite keeps handing out ever-higher ids from this table unless
            # it is reset too, which makes a fresh database look like it has
            # already seen 400 rows.
            if not args.source:
                try:
                    cur.execute("DELETE FROM sqlite_sequence "
                                "WHERE name = 'weather_reports'")
                except Exception:
                    pass

    print(f"\ndeleted {total} rows. now run:")
    print("  python main.py fetch --source mastodon")
    print("  python main.py fetch --source openmeteo")


if __name__ == "__main__":
    main()
