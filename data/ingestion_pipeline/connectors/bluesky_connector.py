"""
Bluesky connector.
 
Uses Bluesky's *public* AppView search endpoint
(app.bsky.feed.searchPosts via public.api.bsky.app). This endpoint is
read-only, free, and does not require an account or API key for public
post search as of writing - it's the most "plug and play" real social
source available for this project. If Bluesky changes this (e.g. starts
requiring auth for search), set BLUESKY_SESSION creds and adapt
`_search_live` to log in via com.atproto.server.createSession first.
 
Docs: https://docs.bsky.app/docs/api/app-bsky-feed-search-posts
"""
 
import json
import os
 
from config import BLUESKY_PUBLIC_ENDPOINT, BLUESKY_SEARCH_LIMIT, WEATHER_HASHTAGS, SAMPLE_DATA_DIR
 
SOURCE_NAME = "bluesky"
 
 
def _search_live(query: str, limit: int) -> list:
    import requests
 
    # Bluesky's public AppView rejects requests with a generic/missing
    # User-Agent (basic bot defense) - send a real one, and ask for JSON
    # explicitly, or every query comes back 403 Forbidden.
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OnyxWeatherPipeline/0.1; "
                      "+https://github.com/your-team/onyx-hackathon)",
        "Accept": "application/json",
    }
 
    resp = requests.get(
        BLUESKY_PUBLIC_ENDPOINT,
        params={"q": query, "limit": limit},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("posts", [])
 
 
def _post_to_raw(post: dict) -> dict:
    record = post.get("record", {}) or {}
    author = post.get("author", {}) or {}
    embed = post.get("embed", {}) or {}
 
    media_urls = []
    images = embed.get("images") or []
    for img in images:
        url = img.get("fullsize") or img.get("thumb")
        if url:
            media_urls.append(url)
 
    uri = post.get("uri", "")  # at://did/app.bsky.feed.post/rkey
    handle = author.get("handle")
    rkey = uri.rsplit("/", 1)[-1] if uri else None
    permalink = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else None
 
    return {
        "source": SOURCE_NAME,
        "source_post_id": uri or post.get("cid"),
        "source_url": permalink,
        "author": handle,
        "text_raw": record.get("text", ""),
        "posted_at": record.get("createdAt"),
        "location_hint": None,  # Bluesky posts rarely carry structured geo
        "media_urls": media_urls,
        "media_type": "photo" if media_urls else "none",
        "language": (record.get("langs") or [None])[0],
        "extra": post,
    }
 
 
def fetch(demo: bool = False) -> list:
    if demo:
        path = os.path.join(SAMPLE_DATA_DIR, "bluesky_sample.json")
        with open(path, "r", encoding="utf-8") as f:
            posts = json.load(f)
        return [_post_to_raw(p) for p in posts]
 
    results = []
    seen_ids = set()
    for tag in WEATHER_HASHTAGS:
        try:
            posts = _search_live(f"#{tag}", BLUESKY_SEARCH_LIMIT)
        except Exception as exc:  # network issues, rate limits, API changes
            print(f"[bluesky] query '#{tag}' failed: {exc}")
            continue
        for p in posts:
            pid = p.get("uri") or p.get("cid")
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            results.append(_post_to_raw(p))
    return results
