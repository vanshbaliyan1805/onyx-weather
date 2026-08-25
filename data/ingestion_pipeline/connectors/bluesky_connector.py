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

from config import (
    BLUESKY_PUBLIC_ENDPOINT,
    BLUESKY_PDS_ENDPOINT,
    BLUESKY_IDENTIFIER,
    BLUESKY_APP_PASSWORD,
    BLUESKY_SEARCH_LIMIT,
    WEATHER_HASHTAGS,
    SAMPLE_DATA_DIR,
)

SOURCE_NAME = "bluesky"

_UA = ("Mozilla/5.0 (compatible; OnyxWeatherPipeline/0.1; "
       "+https://github.com/your-team/onyx-hackathon)")

# Access token cached for the duration of one fetch() run. We search ~22
# hashtags per run; logging in once per query would be both slow and a good
# way to get rate-limited.
_session_token = None


def credentials_present() -> bool:
    return bool(BLUESKY_IDENTIFIER and BLUESKY_APP_PASSWORD)


def _login(attempts: int = 3) -> str:
    """
    Exchange handle + app password for an access token.

    Bluesky routes app.bsky.* calls through the user's PDS, so we authenticate
    here and then issue searches against the same host. Returns the accessJwt.

    Retries on timeouts/connection errors - bsky.social is frequently slow and
    a single 20s attempt fails often enough to be worth backing off and
    retrying rather than declaring the source dead for the whole run.
    """
    import time
    import requests

    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(
                f"{BLUESKY_PDS_ENDPOINT}/xrpc/com.atproto.server.createSession",
                json={"identifier": BLUESKY_IDENTIFIER, "password": BLUESKY_APP_PASSWORD},
                headers={"User-Agent": _UA, "Content-Type": "application/json"},
                timeout=60,
            )
            break
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt < attempts:
                wait = attempt * 5
                print(f"[bluesky] login attempt {attempt}/{attempts} timed out, "
                      f"retrying in {wait}s...")
                time.sleep(wait)
    else:
        raise RuntimeError(
            f"Could not reach {BLUESKY_PDS_ENDPOINT} after {attempts} attempts "
            f"({last_exc}). Check your internet connection, or whether a "
            f"firewall/ISP is blocking bsky.social."
        )

    if resp.status_code == 401:
        raise RuntimeError(
            "Bluesky rejected the login. Check BLUESKY_IDENTIFIER (your handle, "
            "e.g. name.bsky.social) and BLUESKY_APP_PASSWORD (an APP PASSWORD "
            "from Settings -> Privacy and Security -> App Passwords, NOT your "
            "account password)."
        )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("accessJwt")
    if not token:
        raise RuntimeError(f"Login succeeded but returned no accessJwt: {data}")
    return token


def _search_authenticated(query: str, limit: int) -> list:
    """Search via the PDS with a Bearer token. This is the path that works."""
    import requests

    global _session_token
    if _session_token is None:
        _session_token = _login()

    def _do(token):
        return requests.get(
            f"{BLUESKY_PDS_ENDPOINT}/xrpc/app.bsky.feed.searchPosts",
            params={"q": query, "limit": limit},
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": _UA,
                "Accept": "application/json",
            },
            timeout=45,
        )

    resp = _do(_session_token)

    # Token expired mid-run - re-login once and retry before giving up.
    if resp.status_code == 401:
        _session_token = _login()
        resp = _do(_session_token)

    resp.raise_for_status()
    return resp.json().get("posts", [])


def _search_public(query: str, limit: int) -> list:
    """
    Unauthenticated fallback. Currently 403s for everyone - kept so the
    connector starts working again on its own if Bluesky fixes the bug.
    """
    import requests

    resp = requests.get(
        BLUESKY_PUBLIC_ENDPOINT,
        params={"q": query, "limit": limit},
        headers={"User-Agent": _UA, "Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("posts", [])


def _search_live(query: str, limit: int) -> list:
    if credentials_present():
        return _search_authenticated(query, limit)
    return _search_public(query, limit)


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

    global _session_token
    _session_token = None  # fresh token per run

    if credentials_present():
        # Fail fast with a clear message rather than printing the same login
        # error 22 times, once per hashtag.
        try:
            _session_token = _login()
            print(f"[bluesky] authenticated as {BLUESKY_IDENTIFIER}")
        except Exception as exc:
            print(f"[bluesky] login failed, skipping: {exc}")
            return []
    else:
        print("[bluesky] no credentials set - trying the public endpoint, which "
              "is currently broken upstream. Set BLUESKY_IDENTIFIER and "
              "BLUESKY_APP_PASSWORD in .env to use the working authenticated path.")

    results = []
    seen_ids = set()
    failures = 0
    for tag in WEATHER_HASHTAGS:
        try:
            posts = _search_live(f"#{tag}", BLUESKY_SEARCH_LIMIT)
        except Exception as exc:  # network issues, rate limits, API changes
            failures += 1
            # Only report the first couple - 22 identical tracebacks is noise.
            if failures <= 2:
                print(f"[bluesky] query '#{tag}' failed: {exc}")
            elif failures == 3:
                print(f"[bluesky] (further query failures suppressed)")
            continue
        for p in posts:
            pid = p.get("uri") or p.get("cid")
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            results.append(_post_to_raw(p))

    if failures:
        print(f"[bluesky] {failures}/{len(WEATHER_HASHTAGS)} queries failed")
    return results
