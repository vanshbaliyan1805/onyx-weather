"""
Mastodon connector.

Uses the public hashtag timeline endpoint:
    GET /api/v1/timelines/tag/:hashtag
which is publicly readable (no auth) on virtually every instance -
this is the same endpoint the "#hashtag" pages on a Mastodon instance's
website use. Queried across a small list of large instances since the
fediverse is decentralized and no single instance has "all" posts.

Docs: https://docs.joinmastodon.org/methods/timelines/#tag
"""

import json
import os
import re

from config import MASTODON_INSTANCES, MASTODON_TIMELINE_LIMIT, WEATHER_HASHTAGS, SAMPLE_DATA_DIR

SOURCE_NAME = "mastodon"
HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return HTML_TAG_RE.sub(" ", html)


def _fetch_tag_live(instance: str, tag: str, limit: int) -> list:
    import requests

    # Same defensive header as the Bluesky connector - some instances
    # (and any CDN/WAF in front of them) reject a generic User-Agent.
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OnyxWeatherPipeline/0.1; "
                      "+https://github.com/your-team/onyx-hackathon)",
        "Accept": "application/json",
    }

    url = f"https://{instance}/api/v1/timelines/tag/{tag}"
    resp = requests.get(url, params={"limit": limit}, headers=headers, timeout=15)
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

    results = []
    seen_ids = set()
    for instance in MASTODON_INSTANCES:
        for tag in WEATHER_HASHTAGS:
            try:
                statuses = _fetch_tag_live(instance, tag, MASTODON_TIMELINE_LIMIT)
            except Exception as exc:
                print(f"[mastodon] {instance} #{tag} failed: {exc}")
                continue
            for s in statuses:
                sid = (instance, s.get("id"))
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                results.append(_status_to_raw(s))
    return results
