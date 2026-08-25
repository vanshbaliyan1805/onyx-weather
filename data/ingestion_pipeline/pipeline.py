"""
pipeline.py
-----------
Orchestrates: connector.fetch() -> cleaning.normalize_record() -> db.insert_record()

This is the file that ties everything together. `main.py` is just a thin
CLI wrapper around `run_pipeline()`.
"""

import time

import db
from config import REQUIRE_INDIAN_LOCATION
from cleaning import normalize_record, is_too_old, parse_timestamp
from connectors import (
    openmeteo_connector,
    mastodon_connector,
    rss_connector,
    bluesky_connector,
    citizen_connector,
)

CONNECTORS = {
    "openmeteo": openmeteo_connector,
    "mastodon": mastodon_connector,
    "rss": rss_connector,
    "bluesky": bluesky_connector,
    "citizen": citizen_connector,
}

# Sources that run when you don't pass --source explicitly.
#
# bluesky needs BLUESKY_IDENTIFIER + BLUESKY_APP_PASSWORD in .env; without
# them it skips itself with a clear message rather than failing the run.
# Everything else is fully keyless.
DEFAULT_SOURCES = ["openmeteo", "mastodon", "rss", "bluesky", "citizen"]


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

        stats = {"fetched": 0, "inserted": 0, "flagged_duplicate": 0,
                 "duplicate_source": 0, "too_old": 0, "no_date": 0,
                 "no_location": 0, "errors": 0}
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
                # Track rows whose timestamp we couldn't parse. These BYPASS the
                # age filter (we'd rather keep a questionable row than silently
                # drop good data), so a high count here means old content may be
                # slipping in unchecked - worth investigating, not ignoring.
                if parse_timestamp(normalized["posted_at"]) is None:
                    stats["no_date"] += 1

                # drop stale content (see MAX_CONTENT_AGE_HOURS in config.py)
                if is_too_old(normalized["posted_at"]):
                    stats["too_old"] += 1
                    continue

                # drop anything we couldn't place in India (REQUIRE_INDIAN_LOCATION).
                # Hashtag timelines are global; this is a national platform.
                if REQUIRE_INDIAN_LOCATION and not normalized["state"]:
                    stats["no_location"] += 1
                    continue
                result = db.insert_record(normalized, db_path=db_path)
                stats[result] = stats.get(result, 0) + 1
            except Exception as exc:
                stats["errors"] += 1
                print(f"[pipeline] {name} record failed to normalize/insert: {exc}")

        elapsed = time.time() - start
        print(f"[pipeline] {name}: fetched={stats['fetched']} inserted={stats['inserted']} "
              f"flagged_duplicate={stats['flagged_duplicate']} duplicate_source={stats['duplicate_source']} "
              f"too_old={stats['too_old']} no_location={stats['no_location']} "
              f"no_date={stats['no_date']} errors={stats['errors']} ({elapsed:.1f}s)")
        summary[name] = stats

    return summary
