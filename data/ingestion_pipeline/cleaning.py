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
import html
import re
from datetime import datetime, timezone

from config import (
    EVENT_CATEGORY_KEYWORDS,
    DEFAULT_EVENT_CATEGORY,
    INDIAN_CITIES,
    INDIAN_STATES,
    MAX_CONTENT_AGE_HOURS,
)

# Matches normal URLs AND the space-mangled ones some feeds emit
# ("https:// english.mathrubhumi.com/news/..."), where a naive \S+ stops at
# the space and leaves a bare "https://" fragment behind. That fragment then
# appears in real rows and never in synthetic ones - a leak that has nothing
# to do with the content.
URL_RE = re.compile(r"(?:https?://|www\.)\s*\S*(?:\s+\S+\.\S+)*", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")

# Repair the damage tag-stripping does to things that were split across tags.
SPLIT_SCHEME_RE = re.compile(r"(https?://|www\.)\s+", re.IGNORECASE)
SPLIT_HASHTAG_RE = re.compile(r"#\s+(\w)")
HASHTAG_RE = re.compile(r"#(\w+)")
MENTION_RE = re.compile(r"@\w+")
WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")

# Lowercased lookup so "Mumbai", "MUMBAI", "mumbai" all match.
_CITY_LOOKUP = {name.lower(): value for name, value in INDIAN_CITIES.items()}
_STATE_LOOKUP = {s.lower(): s for s in INDIAN_STATES}

# Place names that are also common words, names, or foreign cities. Matching
# these alone produces real errors:
#
#   "wo chala gaya tha"        -> Gaya, Bihar        (Hindi for "went")
#   "vegetables at the mandi"  -> Mandi, HP          (Hindi for "market")
#   "Salem Oregon flooding"    -> Salem, Tamil Nadu  (wrong continent)
#
# These are all real Indian places we want to keep, so the fix isn't to drop
# them - it's to require corroboration. An ambiguous name only counts if the
# text ALSO shows an India signal: an explicit mention of India/IMD, or a
# second, unambiguous Indian place name.
AMBIGUOUS_PLACES = {
    "gaya", "mandi", "salem", "sagar", "hassan", "pali", "puri", "kota",
    "daman", "diu", "leh", "vasco", "satara", "bastar", "goa", "mathura","salt lake"
}

# Words that independently establish the text is about India.
INDIA_SIGNALS = ("india", "indian", "imd", "bharat", "monsoon")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value):
    """
    Parse a timestamp from any format our sources actually emit.

    This handles TWO different standards, and getting that wrong is a real
    trap: RSS/Atom feeds emit RFC-2822 dates ('Sat, 23 Aug 2025 05:00:00
    +0530'), while APIs emit ISO-8601 ('2025-08-23T05:00:00Z'). An
    ISO-only parser silently returns None for every RSS row, which - given
    that unparseable dates are kept rather than dropped - lets year-old
    articles walk straight past the max-age filter.

    Returns a timezone-aware datetime, or None if genuinely unparseable.
    """
    if not value:
        return None
    text = str(value).strip()

    # ISO-8601 (APIs: Mastodon, Bluesky, Open-Meteo, citizen reports)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    # RFC-2822 (RSS/Atom feeds)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(text)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass

    return None


def to_utc_iso(value) -> str:
    """
    Normalize any timestamp a connector hands us into a single canonical form:
    ISO-8601, in UTC, with an explicit '+00:00' offset.

    This is the last line of defence before the database. `posted_at` is
    TIMESTAMPTZ NOT NULL in PostgreSQL, and a naive string there is not an
    error - Postgres just interprets it in the *server's* timezone (UTC on
    Supabase) and stores a silently wrong instant. An RSS feed's RFC-2822
    date would be a hard insert failure. Neither can happen if every row
    leaves cleaning.py in the same shape.

    Doing it here rather than in each connector means a source added later
    inherits the guarantee for free. Unparseable input falls back to "now",
    which is honest for a real-time pipeline and keeps the NOT NULL contract.
    """
    dt = parse_timestamp(value)
    if dt is None:
        return utc_now_iso()
    return dt.astimezone(timezone.utc).isoformat()


def is_too_old(posted_at) -> bool:
    """
    True if this content is older than MAX_CONTENT_AGE_HOURS.

    Hashtag timelines and RSS feeds happily return content from weeks ago.
    For a real-time platform that's noise, and it quietly poisons ML training
    data with stale events. Unparseable timestamps are KEPT rather than
    dropped - better to let a questionable row through than silently discard
    good data because one source used an odd date format.
    """
    if MAX_CONTENT_AGE_HOURS is None:
        return False
    dt = parse_timestamp(posted_at)
    if dt is None:
        return False
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    return age_hours > MAX_CONTENT_AGE_HOURS


def extract_hashtags(text: str) -> list:
    if not text:
        return []
    return sorted(set(h.lower() for h in HASHTAG_RE.findall(text)))


def clean_text(text: str) -> str:
    """
    Produce clean, comparable text for downstream ML and display.

    Removes anything that is an artefact of HOW a record was transported
    rather than WHAT it says. That distinction matters: RSS entries arrive
    carrying HTML tags and escaped entities, Mastodon posts arrive as HTML,
    social text carries URLs. None of that is content, but all of it is
    perfectly correlated with the source - so a classifier trained on
    uncleaned text learns to spot '<img' and 'RSS' rather than learning
    anything about the claim.

    Order matters here:
      1. unescape entities first  (&amp;lt;p&amp;gt; -> <p>) so step 2 can see them
      2. strip HTML tags
      3. strip URLs, including the space-mangled ones some feeds emit
      4. strip @mentions
      5. collapse whitespace

    Hashtags are deliberately KEPT - they are content, and the sentence often
    reads correctly only with them in place.
    """
    if not text:
        return ""
    text = html.unescape(text)      # &amp; -> &,  &lt; -> <,  &#39; -> '
    text = html.unescape(text)      # again: some feeds double-escape
    text = HTML_TAG_RE.sub(" ", text)
    # Tags are replaced with a space so words don't run together - but that
    # space also lands INSIDE things that were split across tags. Mastodon
    # wraps every link in three spans (<span>https://</span><span>host/pa</span>
    # <span>th</span>) and every hashtag as #<span>Tag</span>, so tag removal
    # turns them into "https:// host/path" and "# Tag". Rejoin them before the
    # URL pass, or a fragmented URL survives it and becomes a class giveaway.
    text = SPLIT_SCHEME_RE.sub(r"\1", text)
    text = SPLIT_HASHTAG_RE.sub(r"#\1", text)
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


def _has_india_signal(lowered: str) -> bool:
    """
    True if the text independently establishes an Indian context - either an
    explicit India/IMD mention, or an unambiguous Indian place name.

    Used to decide whether an ambiguous place-name match (Gaya, Mandi, Salem)
    should be trusted.
    """
    if any(sig in lowered for sig in INDIA_SIGNALS):
        return True
    for name in _CITY_LOOKUP:
        if name in AMBIGUOUS_PLACES:
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", lowered):
            return True
    for state_lower in _STATE_LOOKUP:
        if re.search(r"\b" + re.escape(state_lower) + r"\b", lowered):
            return True
    return False


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

        # Collect every place name present, splitting confident hits from
        # ones that need corroboration (see AMBIGUOUS_PLACES).
        confident, ambiguous = [], []
        for city_name, (state, lat, lon) in _CITY_LOOKUP.items():
            # word-boundary match to avoid "pune" matching inside another word
            if re.search(r"\b" + re.escape(city_name) + r"\b", lowered):
                (ambiguous if city_name in AMBIGUOUS_PLACES else confident).append(
                    (city_name, state, lat, lon)
                )

        # Prefer the longest confident match - "navi mumbai" beats "mumbai",
        # "greater noida" beats "noida".
        if confident:
            city_name, state, lat, lon = max(confident, key=lambda m: len(m[0]))
            return city_name.title(), state, lat, lon, candidate

        # Only ambiguous names matched. Accept them only if the text
        # independently signals India - otherwise "Salem Oregon" would be
        # filed under Tamil Nadu.
        if ambiguous and _has_india_signal(lowered):
            city_name, state, lat, lon = max(ambiguous, key=lambda m: len(m[0]))
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
    posted_at = to_utc_iso(raw.get("posted_at"))
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
        # Supervised training target: 0 = genuine, 1 = fabricated.
        # Everything this pipeline collects is 0 by definition - it came from
        # a real service. Only a synthetic-data generator sets 1.
        # NOT the same as verification_status - see the note in db.py.
        "ml_label": int(raw.get("ml_label", 0)),
        "raw_json": raw.get("extra"),
    }


# === onyx failsafes: appended by apply_failsafes.py ===
# Place names shared with somewhere else in the world. Being in this set does
# not block a name - it means the name alone is not enough, and something else
# in the post has to corroborate that we are in India.
#
# Salt Lake was the one that bit: eight National Weather Service flash-flood
# alerts from Salt Lake City, Utah were filed under Salt Lake, West Bengal and
# then measurement-checked against Kolkata. Every entry below is a place where
# the same thing can happen.
_EXTRA_AMBIGUOUS = {
    "salt lake", "salem", "kingston", "victoria", "richmond", "oxford",
    "cambridge", "springfield", "aurora", "columbia", "jackson", "franklin",
    "georgetown", "wellington", "hamilton", "london", "birmingham", "perth",
    "newcastle", "windsor", "kent", "surrey", "york", "dover", "bristol",
    "gloucester", "lincoln", "warren", "clinton", "madison", "monroe",
    "arlington", "burlington", "chester", "durham", "essex", "exeter",
    "greenwich", "hastings", "ipswich", "norwich", "preston", "reading",
    "rochester", "somerset", "stratford", "sunderland", "sussex", "wexford",
}
try:
    AMBIGUOUS_PLACES.update(_EXTRA_AMBIGUOUS)
except NameError:
    AMBIGUOUS_PLACES = set(_EXTRA_AMBIGUOUS)
except AttributeError:
    # Defined as a list or tuple rather than a set.
    AMBIGUOUS_PLACES = set(AMBIGUOUS_PLACES) | _EXTRA_AMBIGUOUS
