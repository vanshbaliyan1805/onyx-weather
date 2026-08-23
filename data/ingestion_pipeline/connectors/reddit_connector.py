"""
Reddit connector.

Uses PRAW (official Python Reddit API wrapper) against Reddit's free
Data API tier (script app, read-only, OAuth client-credentials flow).
Free tier as of writing: 100 queries/minute per OAuth client, more than
enough for a hackathon polling loop. You need a free Reddit app to get
REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET - see README.md for the 2-minute
setup steps.

Searches a fixed list of India-relevant subreddits (config.REDDIT_SUBREDDITS)
for our weather keyword list, newest first.
"""

import json
import os

from config import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT,
    REDDIT_SUBREDDITS,
    REDDIT_SEARCH_LIMIT,
    WEATHER_KEYWORDS,
    SAMPLE_DATA_DIR,
)

SOURCE_NAME = "reddit"


def _get_client():
    import praw

    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        raise RuntimeError(
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set. "
            "Create a free 'script' app at https://www.reddit.com/prefs/apps "
            "and set them as environment variables (see README.md)."
        )
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )


def _submission_to_raw(submission) -> dict:
    media_urls = []
    media_type = "none"
    url = getattr(submission, "url", None)
    if url and any(url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif")):
        media_urls.append(url)
        media_type = "photo"
    elif url and any(ext in url.lower() for ext in (".mp4", "v.redd.it")):
        media_urls.append(url)
        media_type = "video"

    text = (submission.title or "") + "\n" + (submission.selftext or "")

    return {
        "source": SOURCE_NAME,
        "source_post_id": submission.id,
        "source_url": f"https://reddit.com{submission.permalink}",
        "author": str(submission.author) if submission.author else None,
        "text_raw": text.strip(),
        "posted_at": _epoch_to_iso(submission.created_utc),
        "location_hint": getattr(submission, "link_flair_text", None),
        "media_urls": media_urls,
        "media_type": media_type,
        "language": None,
        "extra": {
            "subreddit": str(submission.subreddit),
            "score": submission.score,
            "num_comments": submission.num_comments,
            "id": submission.id,
        },
    }


def _epoch_to_iso(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _demo_to_raw(item: dict) -> dict:
    return {
        "source": SOURCE_NAME,
        "source_post_id": item["id"],
        "source_url": f"https://reddit.com{item['permalink']}",
        "author": item.get("author"),
        "text_raw": (item.get("title", "") + "\n" + item.get("selftext", "")).strip(),
        "posted_at": item.get("created_at"),
        "location_hint": item.get("flair"),
        "media_urls": item.get("media_urls", []),
        "media_type": "photo" if item.get("media_urls") else "none",
        "language": None,
        "extra": {"subreddit": item.get("subreddit"), "score": item.get("score")},
    }


def fetch(demo: bool = False) -> list:
    if demo:
        path = os.path.join(SAMPLE_DATA_DIR, "reddit_sample.json")
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        return [_demo_to_raw(i) for i in items]

    try:
        reddit = _get_client()
    except Exception as exc:
        print(f"[reddit] client setup failed, skipping: {exc}")
        return []

    results = []
    seen_ids = set()
    query = " OR ".join(WEATHER_KEYWORDS[:15])  # Reddit search has a query-length limit
    for sub_name in REDDIT_SUBREDDITS:
        try:
            subreddit = reddit.subreddit(sub_name)
            for submission in subreddit.search(query, sort="new", limit=REDDIT_SEARCH_LIMIT):
                if submission.id in seen_ids:
                    continue
                seen_ids.add(submission.id)
                results.append(_submission_to_raw(submission))
        except Exception as exc:
            print(f"[reddit] r/{sub_name} failed: {exc}")
            continue
    return results
