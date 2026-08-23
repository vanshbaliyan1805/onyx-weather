"""
cleaning.py
-----------
All text-cleaning / normalization / light-tagging logic lives here.
 
This module turns whatever a connector fetched (raw, messy, source-specific)
into the flat, unified record shape defined in db.py's SCHEMA. It does NOT
do fake-detection or heavyweight ML dedup - that's the ML teammate's job.
What it does do:
 
  * strip URLs / boilerplate / excess whitespace from text
  * pull out hashtags
  * guess an Indian city + state from the text (falls back to None)
  * guess a rough event category from keywords (a cheap first pass)
  * build a stable dedup hash so obvious duplicates can be flagged before
    handoff
"""
 
import hashlib
import re
from datetime import datetime, timezone
 
from config import EVENT_CATEGORY_KEYWORDS, DEFAULT_EVENT_CATEGORY, INDIAN_CITIES, INDIAN_STATES
 
URL_RE = re.compile(r"https?://\S+|www\.\S+")
HASHTAG_RE = re.compile(r"#(\w+)")
MENTION_RE = re.compile(r"@\w+")
WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
 
# Lowercased lookup so "Mumbai", "MUMBAI", "mumbai" all match.
_CITY_LOOKUP = {name.lower(): value for name, value in INDIAN_CITIES.items()}
_STATE_LOOKUP = {s.lower(): s for s in INDIAN_STATES}
 
 
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
 
 
def extract_hashtags(text: str) -> list:
    if not text:
        return []
    return sorted(set(h.lower() for h in HASHTAG_RE.findall(text)))
 
 
def clean_text(text: str) -> str:
    """Strip URLs/mentions, collapse whitespace. Keeps hashtags in place
    (readable) since the ML teammate may want sentence context intact."""
    if not text:
        return ""
    text = URL_RE.sub("", text)
    text = MENTION_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text
 
 
def guess_event_category(text: str) -> str:
    if not text:
        return DEFAULT_EVENT_CATEGORY
    lowered = text.lower()
    for category, keywords in EVENT_CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in lowered:
                return category
    return DEFAULT_EVENT_CATEGORY
 
 
def guess_location(text: str, explicit_location: str = None):
    """
    Try to find an Indian city (and its state + lat/lon) mentioned in the
    text, or in an explicit location string if the source provided one
    (e.g. a user profile location field or GPS-tagged metadata).
 
    Returns (city, state, lat, lon, location_raw).
    """
    candidates = []
    if explicit_location:
        candidates.append(explicit_location)
    if text:
        candidates.append(text)
 
    for candidate in candidates:
        lowered = candidate.lower()
        for city_name, (state, lat, lon) in _CITY_LOOKUP.items():
            # word-boundary match to avoid "pune" matching inside another word
            if re.search(r"\b" + re.escape(city_name) + r"\b", lowered):
                return city_name.title(), state, lat, lon, candidate
 
    # No city hit - try to at least tag a state
    for candidate in candidates:
        lowered = candidate.lower()
        for state_name_lower, state_name in _STATE_LOOKUP.items():
            if re.search(r"\b" + re.escape(state_name_lower) + r"\b", lowered):
                return None, state_name, None, None, candidate
 
    return None, None, None, None, (explicit_location or None)
 
 
def make_dedup_hash(text: str, city: str, posted_at: str) -> str:
    """
    Cheap, deterministic fingerprint used to flag *obvious* duplicates
    (identical text reposted, same report pulled by two connectors, etc.)
    within our own pipeline run. Normalizes text (lowercase, strip
    hashtags/punctuation) before hashing so near-identical repostings
    still collide.
 
    This is intentionally simple - the ML teammate's fuzzy/semantic dedup
    is the real defense against paraphrased duplicates.
    """
    normalized = (text or "").lower()
    normalized = URL_RE.sub("", normalized)
    normalized = HASHTAG_RE.sub("", normalized)
    normalized = NON_ALNUM_RE.sub("", normalized)
    normalized = WHITESPACE_RE.sub(" ", normalized).strip()
    date_bucket = (posted_at or "")[:10]  # day-level bucket
    fingerprint = f"{normalized}|{(city or '').lower()}|{date_bucket}"
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
 
 
def normalize_record(raw: dict) -> dict:
    """
    Convert a connector's raw dict into the unified schema shape.
    Every connector is responsible for producing a `raw` dict with these
    keys before calling this function:
 
        source, source_post_id, source_url, author, text_raw, posted_at,
        location_hint (optional), media_urls (list), media_type,
        language (optional), extra (dict, anything else worth keeping)
 
    See db.py SCHEMA for the full output column list.
    """
    text_raw = raw.get("text_raw") or ""
    text_clean = clean_text(text_raw)
    hashtags = extract_hashtags(text_raw)
    city, state, lat, lon, location_raw = guess_location(
        text_raw, raw.get("location_hint")
    )
    # A connector that KNOWS the category (Open-Meteo derives it from measured
    # precipitation/temperature/wind, not from words) may pass it explicitly.
    # Measurement beats keyword-matching, so an explicit value always wins.
    event_category_guess = raw.get("event_category") or guess_event_category(text_raw)
    posted_at = raw.get("posted_at") or utc_now_iso()
    dedup_hash = make_dedup_hash(text_clean, city, posted_at)
 
    return {
        "source": raw.get("source"),
        "source_post_id": raw.get("source_post_id"),
        "source_url": raw.get("source_url"),
        "author": raw.get("author"),
        "text_raw": text_raw,
        "text_clean": text_clean,
        "hashtags": ",".join(hashtags),
        "posted_at": posted_at,
        "ingested_at": utc_now_iso(),
        "city": city,
        "state": state,
        "latitude": lat,
        "longitude": lon,
        "location_raw": location_raw,
        "media_urls": ",".join(raw.get("media_urls") or []),
        "media_type": raw.get("media_type") or ("photo" if raw.get("media_urls") else "none"),
        "event_category_guess": event_category_guess,
        "language": raw.get("language"),
        "dedup_hash": dedup_hash,
        "is_likely_duplicate": 0,  # filled in by db.insert_record at write time
        # Connectors may override this. Almost everything stays 'unverified'
        # until the ML pipeline / admin panel rules on it - the exception is
        # authoritative sources like Open-Meteo, which mark themselves
        # 'verified' because they are measurements, not claims.
        "verification_status": raw.get("verification_status") or "unverified",
        "raw_json": raw.get("extra"),
    }