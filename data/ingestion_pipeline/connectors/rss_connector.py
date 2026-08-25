"""
RSS / news-website connector.

Covers the "websites" data source in the problem statement. Pulls from a
configurable list of Indian news RSS feeds (config.RSS_FEEDS) and keeps
only entries whose title/summary mention a weather keyword. No API key
needed, no rate limits to speak of - RSS is about as friendly as data
sources get.
"""

import json
import os

from config import RSS_FEEDS, WEATHER_KEYWORDS, SAMPLE_DATA_DIR

SOURCE_NAME = "rss"


def _matches_weather_keywords(text: str) -> bool:
    lowered = (text or "").lower()
    return any(kw in lowered for kw in WEATHER_KEYWORDS)


def _entry_to_raw(entry, feed_name: str) -> dict:
    summary = getattr(entry, "summary", "") if hasattr(entry, "summary") else entry.get("summary", "")
    title = getattr(entry, "title", "") if hasattr(entry, "title") else entry.get("title", "")
    link = getattr(entry, "link", "") if hasattr(entry, "link") else entry.get("link", "")
    # Date handling. feedparser exposes BOTH a raw RFC-2822 string
    # ('published') and an already-parsed struct_time ('published_parsed').
    # Prefer the parsed one and convert it to ISO-8601 here, so every row in
    # the database carries a consistent timestamp format regardless of source.
    #
    # This matters: feeds emit RFC-2822, APIs emit ISO-8601. Storing the raw
    # feed string means downstream date filtering has to handle two standards,
    # and anything that only handles ISO will silently treat every RSS row as
    # having no date - letting arbitrarily old articles through.
    published = None
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None) if hasattr(entry, attr) else entry.get(attr)
        if parsed:
            try:
                from calendar import timegm
                from datetime import datetime, timezone
                published = datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).isoformat()
                break
            except (TypeError, ValueError, OverflowError):
                pass

    # Fall back to the raw string only if the parsed form was missing/bad.
    # cleaning.parse_timestamp understands RFC-2822, so this still works.
    if not published:
        for attr in ("published", "updated"):
            val = getattr(entry, attr, None) if hasattr(entry, attr) else entry.get(attr)
            if val:
                published = val
                break

    media_urls = []
    media_content = getattr(entry, "media_content", None) if hasattr(entry, "media_content") else entry.get("media_content")
    if media_content:
        media_urls = [m.get("url") for m in media_content if m.get("url")]

    text_raw = f"{title}\n{summary}".strip()

    return {
        "source": SOURCE_NAME,
        "source_post_id": link,
        "source_url": link,
        "author": feed_name,
        "text_raw": text_raw,
        "posted_at": published,
        "location_hint": None,
        "media_urls": media_urls,
        "media_type": "photo" if media_urls else "none",
        "language": "en",
        "extra": {"feed": feed_name},
    }


def fetch(demo: bool = False) -> list:
    if demo:
        path = os.path.join(SAMPLE_DATA_DIR, "rss_sample.json")
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        results = []
        for item in items:
            raw = _entry_to_raw(item, item.get("feed", "demo-feed"))
            if _matches_weather_keywords(raw["text_raw"]):
                results.append(raw)
        return results

    import feedparser

    results = []
    for feed_cfg in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_cfg["url"])
        except Exception as exc:
            print(f"[rss] {feed_cfg['name']} failed: {exc}")
            continue
        for entry in parsed.entries:
            raw = _entry_to_raw(entry, feed_cfg["name"])
            if _matches_weather_keywords(raw["text_raw"]):
                results.append(raw)
    return results
