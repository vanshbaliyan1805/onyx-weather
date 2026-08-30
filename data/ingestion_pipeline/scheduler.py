"""
scheduler.py
------------
Runs the pipeline continuously on two independent schedules.

    python scheduler.py

Leave it running. Ctrl+C to stop cleanly.

WHY TWO SCHEDULES
-----------------
Open-Meteo's record ID is `city-timestamp`, and its model advances every 15
minutes - so polling it every 15 minutes produces ~289 genuinely new rows
each time. Over a night that is tens of thousands of measured readings, which
drowns the social and news records (a few hundred at most) and leaves the
database ~98% one source.

So: Open-Meteo runs hourly (still a proper time series, a quarter the bulk),
everything else runs every 15 minutes (news breaks at news pace, and catching
it quickly is the whole point).

DUPLICATES
----------
Nothing re-enters the database. Two layers already handle it:

  1. UNIQUE(source, source_post_id) in the schema - the same post from the
     same source can physically only exist once.
  2. dedup_hash - near-identical text from a DIFFERENT source is inserted but
     flagged is_likely_duplicate=1 rather than silently dropped, so the ML
     stage can still see that a claim appeared in two places.

Re-fetching unchanged content is therefore cheap and safe. Expect most runs
to report high `duplicate_source` and low `inserted` - that is the system
working, not failing.

LOGGING
-------
Everything goes to the console AND to scheduler.log, so you can review what
happened overnight without having kept the window in view.
"""

import signal
import sys
import time
from datetime import datetime, timezone

import db
from pipeline import run_pipeline

# --- schedules, in seconds -------------------------------------------------
FAST_SOURCES = ["mastodon", "rss", "bluesky", "citizen"]
FAST_INTERVAL = 15 * 60          # 15 minutes

SLOW_SOURCES = ["openmeteo"]
SLOW_INTERVAL = 60 * 60          # 1 hour

LOG_FILE = "scheduler.log"

# How long a gap counts as "the laptop slept". After a sleep we run once
# immediately rather than trying to replay every interval we missed.
SLEEP_GAP_THRESHOLD = 3 * 60 * 60

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True
    log("")
    log("Stop requested - finishing the current run, then exiting.")


def log(message: str):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {message}" if message else ""
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # never let a logging failure kill the collector


def run_batch(label: str, sources: list) -> dict:
    """One pipeline run. Never raises - a crashed source must not stop the loop."""
    try:
        before = db.count_records()
    except Exception as exc:
        log(f"[{label}] db count failed before run: {exc}")
        return {}

    try:
        summary = run_pipeline(sources=sources)
    except Exception as exc:
        log(f"[{label}] run failed: {exc}")
        return {}
        
    try:
        after = db.count_records()
    except Exception as exc:
        log(f"[{label}] db count failed after run: {exc}")
        return summary

    added = after - before
    fetched = sum(s.get("fetched", 0) for s in summary.values())
    dupes = sum(s.get("duplicate_source", 0) for s in summary.values())
    old = sum(s.get("too_old", 0) for s in summary.values())
    noloc = sum(s.get("no_location", 0) for s in summary.values())

    log(f"[{label}] +{added} new  (saw {fetched}, {dupes} already had, "
        f"{old} too old, {noloc} not India)  ->  {after} total")
    return summary


def main():
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    db.init_db()

    log("=" * 70)
    log("Onyx collector started")
    log(f"  fast : {', '.join(FAST_SOURCES)}  every {FAST_INTERVAL // 60} min")
    log(f"  slow : {', '.join(SLOW_SOURCES)}  every {SLOW_INTERVAL // 60} min")
    log(f"  log  : {LOG_FILE}")
    log(f"  rows : {db.count_records()} at start")
    log("  Ctrl+C to stop")
    log("=" * 70)

    started = time.time()
    rows_at_start = db.count_records()

    # Run both immediately so there's data within seconds of starting.
    next_fast = next_slow = time.time()
    last_tick = time.time()

    while not _stop:
        now = time.time()

        # If the clock jumped forward a long way the machine was asleep.
        # Reset the schedule instead of firing every missed interval at once.
        if now - last_tick > SLEEP_GAP_THRESHOLD:
            log(f"Gap of {(now - last_tick) / 3600:.1f}h detected "
                f"(machine asleep?) - resuming from now.")
            next_fast = next_slow = now
        last_tick = now

        if now >= next_slow:
            run_batch("slow", SLOW_SOURCES)
            next_slow = now + SLOW_INTERVAL

        if _stop:
            break

        if now >= next_fast:
            run_batch("fast", FAST_SOURCES)
            next_fast = now + FAST_INTERVAL

        # Sleep in short slices so Ctrl+C responds promptly.
        wake_at = min(next_fast, next_slow)
        while not _stop and time.time() < wake_at:
            time.sleep(min(5, max(0.5, wake_at - time.time())))

    total = db.count_records()
    hours = (time.time() - started) / 3600
    log("=" * 70)
    log(f"Collector stopped after {hours:.1f}h")
    log(f"  rows at start : {rows_at_start}")
    log(f"  rows now      : {total}")
    log(f"  collected     : +{total - rows_at_start}")
    log("=" * 70)


if __name__ == "__main__":
    main()
