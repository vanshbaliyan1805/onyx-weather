"""
Mastodon connector.

Uses the public hashtag timeline endpoint:
    GET /api/v1/timelines/tag/:hashtag
which is publicly readable (no auth) on virtually every instance -
this is the same endpoint the "#hashtag" pages on a Mastodon instance's
website use. Queried across a small list of large instances since the
fediverse is decentralized and no single instance has "all" posts.

Docs: https://docs.joinmastodon.org/methods/timelines/#tag

SPEED
-----
One request per (instance, hashtag). With 73 tags and 2 instances that is
146 requests, and run one at a time at ~2.7s each it took six to seven
minutes with no output until the very end - long enough that it looked
hung. Three changes:

  * a thread pool, so the requests overlap instead of queueing
  * one requests.Session per worker, so the TLS handshake is paid once per
    host instead of 73 times
  * an 8s timeout instead of 15s, because a healthy instance answers in
    under three and a slow one is not worth waiting on

Concurrency is deliberately modest. Mastodon instances rate-limit by IP
(mastodon.social allows 300 requests per 5 minutes on public endpoints),
and hammering them harder gets you 429s, which is slower than being polite.
8 workers puts 146 requests through in about 50 seconds.

Set ONYX_FETCH_WORKERS to change it, ONYX_FAST_FETCH=1 in config.py to cut
the tag list down for live demos.
"""

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (MASTODON_INSTANCES, MASTODON_TIMELINE_LIMIT,
                    WEATHER_HASHTAGS, SAMPLE_DATA_DIR)

SOURCE_NAME = "mastodon"
HTML_TAG_RE = re.compile(r"<[^>]+>")

WORKERS = int(os.environ.get("ONYX_FETCH_WORKERS", "8"))
TIMEOUT = float(os.environ.get("ONYX_FETCH_TIMEOUT", "8"))

HEADERS = {
    # Same defensive header as the Bluesky connector - some instances
    # (and any CDN/WAF in front of them) reject a generic User-Agent.
    "User-Agent": "Mozilla/5.0 (compatible; OnyxWeatherPipeline/0.1; "
                  "+https://github.com/your-team/onyx-hackathon)",
    "Accept": "application/json",
}

# One Session per thread. Sessions are not documented as thread-safe, so
# they are kept in thread-local storage rather than shared.
_local = threading.local()


def _session():
    import requests
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(HEADERS)
    return _local.s


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return HTML_TAG_RE.sub(" ", html)


def _fetch_tag_live(instance: str, tag: str, limit: int) -> list:
    url = f"https://{instance}/api/v1/timelines/tag/{tag}"
    resp = _session().get(url, params={"limit": limit}, timeout=TIMEOUT)
    # 429 means we are going too fast. Skipping one tag is much cheaper than
    # backing off and dragging the whole run out, and the next fetch will
    # pick up anything missed.
    if resp.status_code == 429:
        raise RuntimeError("rate limited (429)")
    resp.raise_for_status()
    return resp.json()


def _status_to_raw(status: dict) -> dict:
    account = status.get("account", {}) or {}
    media_urls = []
    media_type = "none"
    for attachment in status.get("media_attachments", []) or []:
        url = attachment.get("url") or attachment.get("preview_url")
        if url:
            media_urls.append(url)
            media_type = attachment.get("type", "photo")

    return {
        "source": SOURCE_NAME,
        "source_post_id": status.get("id") or status.get("uri"),
        "source_url": status.get("url") or status.get("uri"),
        "author": account.get("acct"),
        "text_raw": _strip_html(status.get("content", "")),
        "posted_at": status.get("created_at"),
        "location_hint": None,
        "media_urls": media_urls,
        "media_type": media_type,
        "language": status.get("language"),
        "extra": status,
    }


def fetch(demo: bool = False) -> list:
    if demo:
        path = os.path.join(SAMPLE_DATA_DIR, "mastodon_sample.json")
        with open(path, "r", encoding="utf-8") as f:
            statuses = json.load(f)
        return [_status_to_raw(s) for s in statuses]

    jobs = [(i, t) for i in MASTODON_INSTANCES for t in WEATHER_HASHTAGS]
    print(f"[mastodon] {len(jobs)} requests "
          f"({len(WEATHER_HASHTAGS)} tags x {len(MASTODON_INSTANCES)} "
          f"instances), {WORKERS} at a time")

    results, seen_ids = [], set()
    done = failed = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(_fetch_tag_live, inst, tag, MASTODON_TIMELINE_LIMIT):
                (inst, tag)
            for inst, tag in jobs
        }
        for fut in as_completed(futures):
            instance, tag = futures[fut]
            done += 1
            try:
                statuses = fut.result()
            except Exception as exc:
                failed += 1
                print(f"[mastodon] {instance} #{tag} failed: {exc}")
                continue
            # Appends happen here on the main thread as futures complete,
            # so `results` and `seen_ids` are never touched concurrently.
            for s in statuses:
                sid = (instance, s.get("id"))
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                results.append(_status_to_raw(s))
            if done % 20 == 0 or done == len(jobs):
                print(f"[mastodon]   {done}/{len(jobs)} requests, "
                      f"{len(results)} posts, {failed} failed")

    return results
