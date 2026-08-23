"""
pipeline.py
-----------
Orchestrates: connector.fetch() -> cleaning.normalize_record() -> db.insert_record()
 
This is the file that ties everything together. `main.py` is just a thin
CLI wrapper around `run_pipeline()`.
"""
 
import time
 
import db
from cleaning import normalize_record
from connectors import (
    bluesky_connector,
    mastodon_connector,
    reddit_connector,
    rss_connector,
    citizen_connector,
    openmeteo_connector,
)
 
CONNECTORS = {
    "openmeteo": openmeteo_connector,
    "mastodon": mastodon_connector,
    "rss": rss_connector,
    "citizen": citizen_connector,
    "bluesky": bluesky_connector,
    "reddit": reddit_connector,
}
 
# Sources that run when you don't pass --source explicitly.
#
# Two connectors are deliberately EXCLUDED here. Both files are kept intact
# and both still work via `--source <name>` - they are excluded because of
# platform-side access restrictions, not because of anything in this code:
#
#   bluesky - its public search endpoint returns 403 Forbidden for every
#             unauthenticated query. Known upstream bug on Bluesky's side:
#             https://github.com/bluesky-social/bsky-docs/issues/332
#             Re-enable by adding "bluesky" back to this list if they fix it.
#
#   reddit  - Reddit has closed off self-serve app creation for the legacy
#             Data API. New apps now require submitting a request that is
#             reviewed manually and gated on moderation use cases, which a
#             research/analytics pipeline does not qualify for. The connector
#             is complete and will work immediately if credentials are ever
#             obtained - it just cannot be provisioned on demand.
DEFAULT_SOURCES = ["openmeteo", "mastodon", "rss", "citizen"]
 
 
def run_pipeline(sources: list = None, demo: bool = False, db_path: str = None) -> dict:
    """
    Fetch from the requested sources (default: all), clean/normalize every
    record, and write it to the database. Returns a per-source summary
    dict, e.g.:
 
        {
          "bluesky": {"fetched": 4, "inserted": 3, "flagged_duplicate": 1, "duplicate_source": 0, "errors": 0},
          ...
        }
    """
    db_path = db_path or db.DB_PATH
    db.init_db(db_path)
 
    sources = sources or list(DEFAULT_SOURCES)
    summary = {}
 
    for name in sources:
        connector = CONNECTORS.get(name)
        if connector is None:
            print(f"[pipeline] unknown source '{name}', skipping")
            continue
 
        stats = {"fetched": 0, "inserted": 0, "flagged_duplicate": 0, "duplicate_source": 0, "errors": 0}
        start = time.time()
        try:
            raw_records = connector.fetch(demo=demo)
        except Exception as exc:
            print(f"[pipeline] {name} connector crashed: {exc}")
            summary[name] = stats
            continue
 
        stats["fetched"] = len(raw_records)
        for raw in raw_records:
            try:
                normalized = normalize_record(raw)
                # skip totally empty text - nothing useful to store or hand off
                if not normalized["text_clean"]:
                    continue
                result = db.insert_record(normalized, db_path=db_path)
                stats[result] = stats.get(result, 0) + 1
            except Exception as exc:
                stats["errors"] += 1
                print(f"[pipeline] {name} record failed to normalize/insert: {exc}")
 
        elapsed = time.time() - start
        print(f"[pipeline] {name}: fetched={stats['fetched']} inserted={stats['inserted']} "
              f"flagged_duplicate={stats['flagged_duplicate']} duplicate_source={stats['duplicate_source']} "
              f"errors={stats['errors']} ({elapsed:.1f}s)")
        summary[name] = stats
 
    return summary