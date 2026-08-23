"""
connectors/
-----------
One module per data source. Every connector exposes a single function:

    fetch(demo: bool = False) -> list[dict]

Each dict in the returned list is a "raw" record using these keys (not all
required - fill in what the source actually gives you):

    source          str   short source name, e.g. "bluesky"
    source_post_id  str   the platform's native ID for this post
    source_url      str   permalink back to the original post
    author          str   username/handle
    text_raw        str   the post text
    posted_at       str   ISO-8601 timestamp
    location_hint   str   any location text the source provides directly
                          (profile location, place tag, GPS-derived name...)
    media_urls      list  photo/video URLs attached to the post
    media_type      str   'photo' | 'video' | 'none'
    language        str   language code if known
    extra           dict  anything else worth preserving (kept as raw_json)

`cleaning.normalize_record()` turns this into the unified DB row shape.

`demo=True` makes the connector read from sample_data/ instead of calling
the live API - useful for developing/demoing without API keys or network
access (see README.md).
"""
