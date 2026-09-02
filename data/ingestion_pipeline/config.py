"""
config.py
---------
Central configuration for the Onyx weather-data ingestion pipeline.

Nothing in here should require you to touch other files. If you want to
track a new hashtag, add a new city, or add an RSS feed, do it here.

API keys / secrets are read from environment variables (or a local .env
file if you use python-dotenv) - never hardcode secrets in this file.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads a local .env file, if present, into os.environ
except ImportError:
    pass  # python-dotenv not installed - fine, just export env vars manually

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "weather_reports.db")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
SAMPLE_DATA_DIR = os.path.join(BASE_DIR, "sample_data")

# ---------------------------------------------------------------------------
# What we search for
# ---------------------------------------------------------------------------
# Hashtags / keywords used to query each platform. Kept deliberately broad -
# better to over-collect and let cleaning/filtering narrow it down than to
# miss a real report because of a strict tag list.
WEATHER_HASHTAGS = [
    "IMD", "IndianWeather", "rain", "rains", "Mumbairains", "Delhirains",
    "monsoon", "monsoon2026", "flood", "floods", "flooding", "heatwave",
    "heatwaves", "thunderstorm", "cyclone", "duststorm", "fog", "hailstorm",
    "waterlogging", "weatheralert", "IMDWeather", "rainfall",
]

# Same list, but as plain keywords (no leading #) for platforms/feeds where
# hashtag search isn't available (e.g. RSS full-text matching).
WEATHER_KEYWORDS = [w.lower() for w in WEATHER_HASHTAGS] + [
    "downpour", "waterlogged", "landslide", "hailstorm", "dust storm",
    "heat wave", "strong winds", "gusty winds", "orange alert", "red alert",
    "yellow alert", "imd alert",
]

# ---------------------------------------------------------------------------
# Event category keyword map (lightweight, rule-based pre-tagging only -
# the ML teammate owns the real classifier; this just saves them a first
# pass and lets the dashboard show *something* before ML runs).
# Order matters: first matching category wins.
# ---------------------------------------------------------------------------
EVENT_CATEGORY_KEYWORDS = [
    ("snow", ["snow", "snowfall", "snowing", "blizzard", "flurries"]),
    ("flooding", ["flood", "flooded", "flooding", "waterlogging", "waterlogged",
                  "inundat", "overflow", "submerged"]),
    ("thunderstorm", ["thunderstorm", "lightning", "thundershower", "hailstorm", "hail"]),
    ("cyclone", ["cyclone", "cyclonic storm", "depression intensif"]),
    ("heatwave", ["heatwave", "heat wave", "scorching", "extreme heat", "heatstroke"]),
    ("dust_storm", ["dust storm", "duststorm", "dust storm warning", "sandstorm"]),
    ("fog", ["fog", "foggy", "smog", "low visibility"]),
    ("strong_wind", ["strong wind", "gusty wind", "high wind", "squall"]),
    ("rainfall", ["rain", "rains", "raining", "rainfall", "downpour", "monsoon", "drizzle"]),
]
DEFAULT_EVENT_CATEGORY = "other"

# ---------------------------------------------------------------------------
# Bluesky (AT Protocol) - public search endpoint, no API key required for
# read-only public post search.
# ---------------------------------------------------------------------------
# Unauthenticated endpoint. Currently returns 403 for every query - a known
# upstream bug: https://github.com/bluesky-social/bsky-docs/issues/332
# Kept as a fallback in case Bluesky fixes it.
BLUESKY_PUBLIC_ENDPOINT = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"

# Authenticated path - this is what actually works.
#
# Bluesky routes app.bsky.* calls through the user's PDS, so we authenticate
# against bsky.social and then issue searches against the same host with a
# Bearer token, rather than hitting the public AppView directly.
#
# BLUESKY_APP_PASSWORD must be an APP PASSWORD, not your account password.
# Generate one at Settings -> Privacy and Security -> App Passwords. App
# passwords are revocable, can't change your email or delete your account,
# and can be thrown away without touching your real credentials.
BLUESKY_PDS_ENDPOINT = "https://bsky.social"
BLUESKY_IDENTIFIER = os.environ.get("BLUESKY_IDENTIFIER", "")      # handle or email
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")  # xxxx-xxxx-xxxx-xxxx

BLUESKY_SEARCH_LIMIT = 50

# ---------------------------------------------------------------------------
# Mastodon - public hashtag timeline endpoint, no API key required.
# Add/remove instances as needed. Indian-specific instances are sparse, so
# the large general instances are included for reach.
# ---------------------------------------------------------------------------
MASTODON_INSTANCES = [
    "mastodon.social",
    "mstdn.social",
]
MASTODON_TIMELINE_LIMIT = 40

# ---------------------------------------------------------------------------
# RSS / news sources - weather-relevant feeds. No API key required.
# These cover the "websites" data source in the problem statement.
# ---------------------------------------------------------------------------
# Feeds that 404 or time out are logged and skipped, so it is safe to keep
# a broad list here - dead entries cost one warning line, not a crash.
RSS_FEEDS = [
    # --- Weather-specific outlets (highest signal-to-noise) ---
    {"name": "Skymet Weather", "url": "https://www.skymetweather.com/content/feed/"},
    {"name": "Down To Earth - Climate", "url": "https://www.downtoearth.org.in/rss/climate-change"},
    {"name": "Down To Earth - Natural Disasters", "url": "https://www.downtoearth.org.in/rss/natural-disasters"},

    # --- National news ---
    {"name": "TOI - Top Stories", "url": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"},
    {"name": "TOI - India", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms"},
    {"name": "TOI - City", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128932452.cms"},
    {"name": "NDTV - India News", "url": "https://feeds.feedburner.com/ndtvnews-india-news"},
    {"name": "Hindustan Times - India News", "url": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"},
    {"name": "Hindustan Times - Cities", "url": "https://www.hindustantimes.com/feeds/rss/cities/rssfeed.xml"},
    {"name": "The Hindu - National", "url": "https://www.thehindu.com/news/national/feeder/default.rss"},
    {"name": "Indian Express - India", "url": "https://indianexpress.com/section/india/feed/"},
    {"name": "Indian Express - Cities", "url": "https://indianexpress.com/section/cities/feed/"},
    {"name": "News18 - India", "url": "https://www.news18.com/rss/india.xml"},
    {"name": "India Today - India", "url": "https://www.indiatoday.in/rss/1206578"},
    {"name": "Firstpost - India", "url": "https://www.firstpost.com/rss/india.xml"},
    {"name": "Scroll.in", "url": "https://scroll.in/feed"},
    {"name": "Deccan Herald - National", "url": "https://www.deccanherald.com/rss/national.rss"},

    # --- City / regional feeds (where local weather actually gets reported) ---
    {"name": "TOI - Mumbai", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128838597.cms"},
    {"name": "TOI - Delhi", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128839596.cms"},
    {"name": "TOI - Bangalore", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128833038.cms"},
    {"name": "TOI - Chennai", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2950623.cms"},
    {"name": "TOI - Kolkata", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128830821.cms"},
    {"name": "TOI - Hyderabad", "url": "https://timesofindia.indiatimes.com/rssfeeds/-2128816011.cms"},
    {"name": "The Hindu - Kerala", "url": "https://www.thehindu.com/news/national/kerala/feeder/default.rss"},
    {"name": "The Hindu - Tamil Nadu", "url": "https://www.thehindu.com/news/national/tamil-nadu/feeder/default.rss"},
    {"name": "The Hindu - Andhra Pradesh", "url": "https://www.thehindu.com/news/national/andhra-pradesh/feeder/default.rss"},
    {"name": "The Hindu - Telangana", "url": "https://www.thehindu.com/news/national/telangana/feeder/default.rss"},
    {"name": "The Hindu - Karnataka", "url": "https://www.thehindu.com/news/national/karnataka/feeder/default.rss"},
]

# ---------------------------------------------------------------------------
# Open-Meteo - free weather API, NO API KEY, no signup, no approval needed.
# https://open-meteo.com  (free for non-commercial use)
#
# This is our "APIs / public datasets" source from the problem statement, and
# it is the most reliable one in the whole pipeline: it returns authoritative
# current-conditions data for every city in INDIAN_CITIES on every run.
#
# It also does something the social sources can't: it gives the ML teammate
# GROUND TRUTH to cross-check citizen/social reports against. If someone
# posts "massive flooding in Jaipur" and the observed precipitation there is
# 0.0 mm, that mismatch is a strong fake-report signal.
# ---------------------------------------------------------------------------
OPENMETEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

# Current-condition variables to request. Chosen to map onto the event
# categories in the problem statement (rain/flood, heat, wind, fog...).
OPENMETEO_CURRENT_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "visibility",
]

# How many cities to request per HTTP call. Open-Meteo accepts comma-separated
# coordinate lists, so all ~55 cities fit in one or two requests.
OPENMETEO_BATCH_SIZE = 50

# Thresholds used to derive an event category from measured values.
# Loosely aligned with IMD's own advisory thresholds.
OPENMETEO_THRESHOLDS = {
    "heatwave_temp_c": 40.0,       # IMD heatwave threshold for the plains
    "heavy_rain_mm": 7.5,          # mm in the current interval -> heavy rainfall
    "very_heavy_rain_mm": 15.0,    # -> flooding risk
    "strong_wind_kmh": 40.0,       # sustained/gust wind
    "low_visibility_m": 1000.0,    # -> fog
}

# ---------------------------------------------------------------------------
# Maximum age of collected content
# ---------------------------------------------------------------------------
# Social and RSS sources happily return content from weeks ago - a hashtag
# timeline for a quiet tag like #duststorm may surface month-old posts. For a
# real-time platform that is noise, and it pollutes ML training data.
#
# Records older than this are dropped at normalization time. Set to None to
# disable the filter entirely.
MAX_CONTENT_AGE_HOURS = 168  # 1 week

# ---------------------------------------------------------------------------
# Geographic scope - India only
# ---------------------------------------------------------------------------
# This is a NATIONAL platform for India, but hashtag timelines are global: a
# search for #rain returns posts from Manchester and Melbourne alongside
# Mumbai. Those rows are noise for every downstream consumer - they pollute
# the dashboard's location filters and give the ML stage irrelevant examples.
#
# With this on, a record is dropped unless cleaning.guess_location() resolved
# an Indian state for it (either directly, or via a city that maps to one).
#
# TRADE-OFF WORTH KNOWING: location detection is keyword matching against
# INDIAN_CITIES and INDIAN_STATES. A genuinely Indian post that names no city
# or state ("heavy rain here since morning") gets dropped too. If you're
# losing rows you want, the fix is to widen INDIAN_CITIES rather than to turn
# this off - add district names, alternate spellings, and localities.
#
# Set to False to keep everything regardless of location.
REQUIRE_INDIAN_LOCATION = True

# ---------------------------------------------------------------------------
# Citizen reports - simulated "app/web form" intake. In production this
# would be a POST endpoint; for the hackathon it reads a local queue file
# that a simple form (see connectors/citizen_connector.py) appends to.
# ---------------------------------------------------------------------------
CITIZEN_REPORTS_FILE = os.path.join(SAMPLE_DATA_DIR, "citizen_reports_queue.json")

# ---------------------------------------------------------------------------
# Geocoding (optional) - OpenStreetMap Nominatim, free, rate-limited to
# 1 request/sec per their usage policy. Used only as a fallback when we
# cannot match a known city name directly from text.
# ---------------------------------------------------------------------------
ENABLE_LIVE_GEOCODING = os.environ.get("ENABLE_LIVE_GEOCODING", "false").lower() == "true"
NOMINATIM_USER_AGENT = "onyx-weather-pipeline (hackathon project)"
NOMINATIM_RATE_LIMIT_SECONDS = 1.1

# ---------------------------------------------------------------------------
# Indian States (for location tagging)
# ---------------------------------------------------------------------------
INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    "Chandigarh", "Andaman and Nicobar Islands", "Lakshadweep",
    "Dadra and Nagar Haveli and Daman and Diu",
]

# ---------------------------------------------------------------------------
# Indian places -> (state, latitude, longitude)
#
# This list is the single biggest lever on how much data survives the
# REQUIRE_INDIAN_LOCATION filter. Location detection is keyword matching, so
# a post about Thane or Vizag is discarded as "not India" unless the name is
# in here. Widening this list recovers real rows; loosening the filter just
# lets global noise back in.
#
# Coverage: metros and their common alternate/older names, all state and UT
# capitals, tier-2 and tier-3 cities, and the metro localities that actually
# show up in weather reporting ("waterlogging in Andheri", "trees down in
# Koramangala").
#
# Localities are mapped to their parent city's coordinates - close enough for
# a city-level map, and better than dropping the row entirely. If you need
# true locality-level precision later, that's a geocoding job, not a lookup
# table.
#
# TO ADD MORE: just add "name": ("State", lat, lon). Lowercase keys. Matching
# is word-boundary aware, so short names are safe from partial-word hits.
# ---------------------------------------------------------------------------
INDIAN_CITIES = {
    # --- Maharashtra ---
    "mumbai": ("Maharashtra", 19.0760, 72.8777),
    "bombay": ("Maharashtra", 19.0760, 72.8777),
    "navi mumbai": ("Maharashtra", 19.0330, 73.0297),
    "thane": ("Maharashtra", 19.2183, 72.9781),
    "kalyan": ("Maharashtra", 19.2437, 73.1355),
    "dombivli": ("Maharashtra", 19.2094, 73.0870),
    "vasai": ("Maharashtra", 19.4259, 72.8225),
    "virar": ("Maharashtra", 19.4559, 72.8113),
    "mira road": ("Maharashtra", 19.2952, 72.8544),
    "bhiwandi": ("Maharashtra", 19.2969, 73.0629),
    "panvel": ("Maharashtra", 18.9894, 73.1175),
    "pune": ("Maharashtra", 18.5204, 73.8567),
    "poona": ("Maharashtra", 18.5204, 73.8567),
    "pimpri": ("Maharashtra", 18.6298, 73.7997),
    "chinchwad": ("Maharashtra", 18.6298, 73.7997),
    "nagpur": ("Maharashtra", 21.1458, 79.0882),
    "nashik": ("Maharashtra", 19.9975, 73.7898),
    "nasik": ("Maharashtra", 19.9975, 73.7898),
    "aurangabad": ("Maharashtra", 19.8762, 75.3433),
    "chhatrapati sambhajinagar": ("Maharashtra", 19.8762, 75.3433),
    "solapur": ("Maharashtra", 17.6599, 75.9064),
    "kolhapur": ("Maharashtra", 16.7050, 74.2433),
    "amravati": ("Maharashtra", 20.9374, 77.7796),
    "sangli": ("Maharashtra", 16.8524, 74.5815),
    "jalgaon": ("Maharashtra", 21.0077, 75.5626),
    "akola": ("Maharashtra", 20.7002, 77.0082),
    "latur": ("Maharashtra", 18.4088, 76.5604),
    "nanded": ("Maharashtra", 19.1383, 77.3210),
    "ratnagiri": ("Maharashtra", 16.9902, 73.3120),
    "satara": ("Maharashtra", 17.6805, 74.0183),
    "chandrapur": ("Maharashtra", 19.9615, 79.2961),
    "wardha": ("Maharashtra", 20.7453, 78.6022),
    "raigad": ("Maharashtra", 18.5158, 73.1822),
    "palghar": ("Maharashtra", 19.6967, 72.7699),
    "konkan": ("Maharashtra", 17.0000, 73.5000),
    "vidarbha": ("Maharashtra", 21.0000, 78.5000),
    "marathwada": ("Maharashtra", 19.0000, 76.5000),
    # Mumbai localities - common in waterlogging/rain reports
    "andheri": ("Maharashtra", 19.1197, 72.8468),
    "bandra": ("Maharashtra", 19.0596, 72.8295),
    "dadar": ("Maharashtra", 19.0178, 72.8478),
    "kurla": ("Maharashtra", 19.0728, 72.8826),
    "sion": ("Maharashtra", 19.0390, 72.8619),
    "malad": ("Maharashtra", 19.1868, 72.8486),
    "borivali": ("Maharashtra", 19.2307, 72.8567),
    "goregaon": ("Maharashtra", 19.1663, 72.8526),
    "powai": ("Maharashtra", 19.1176, 72.9060),
    "chembur": ("Maharashtra", 19.0522, 72.9005),
    "colaba": ("Maharashtra", 18.9067, 72.8147),
    "worli": ("Maharashtra", 19.0176, 72.8175),
    "juhu": ("Maharashtra", 19.1075, 72.8263),
    "vashi": ("Maharashtra", 19.0771, 72.9986),
    "ghatkopar": ("Maharashtra", 19.0860, 72.9080),
    "mulund": ("Maharashtra", 19.1726, 72.9425),

    # --- Delhi NCR ---
    "delhi": ("Delhi", 28.7041, 77.1025),
    "new delhi": ("Delhi", 28.6139, 77.2090),
    "ncr": ("Delhi", 28.6139, 77.2090),
    "dwarka": ("Delhi", 28.5921, 77.0460),
    "rohini": ("Delhi", 28.7495, 77.0565),
    "saket": ("Delhi", 28.5245, 77.2066),
    "karol bagh": ("Delhi", 28.6519, 77.1909),
    "connaught place": ("Delhi", 28.6315, 77.2167),
    "vasant kunj": ("Delhi", 28.5200, 77.1591),
    "gurugram": ("Haryana", 28.4595, 77.0266),
    "gurgaon": ("Haryana", 28.4595, 77.0266),
    "noida": ("Uttar Pradesh", 28.5355, 77.3910),
    "greater noida": ("Uttar Pradesh", 28.4744, 77.5040),
    "faridabad": ("Haryana", 28.4089, 77.3178),
    "ghaziabad": ("Uttar Pradesh", 28.6692, 77.4538),

    # --- Karnataka ---
    "bangalore": ("Karnataka", 12.9716, 77.5946),
    "bengaluru": ("Karnataka", 12.9716, 77.5946),
    "mysore": ("Karnataka", 12.2958, 76.6394),
    "mysuru": ("Karnataka", 12.2958, 76.6394),
    "mangalore": ("Karnataka", 12.9141, 74.8560),
    "mangaluru": ("Karnataka", 12.9141, 74.8560),
    "hubli": ("Karnataka", 15.3647, 75.1240),
    "hubballi": ("Karnataka", 15.3647, 75.1240),
    "dharwad": ("Karnataka", 15.4589, 75.0078),
    "belgaum": ("Karnataka", 15.8497, 74.4977),
    "belagavi": ("Karnataka", 15.8497, 74.4977),
    "gulbarga": ("Karnataka", 17.3297, 76.8343),
    "kalaburagi": ("Karnataka", 17.3297, 76.8343),
    "davangere": ("Karnataka", 14.4644, 75.9218),
    "bellary": ("Karnataka", 15.1394, 76.9214),
    "shimoga": ("Karnataka", 13.9299, 75.5681),
    "udupi": ("Karnataka", 13.3409, 74.7421),
    "hassan": ("Karnataka", 13.0072, 76.0962),
    "chikmagalur": ("Karnataka", 13.3161, 75.7720),
    "kodagu": ("Karnataka", 12.3375, 75.8069),
    "coorg": ("Karnataka", 12.3375, 75.8069),
    "koramangala": ("Karnataka", 12.9352, 77.6245),
    "whitefield": ("Karnataka", 12.9698, 77.7500),
    "indiranagar": ("Karnataka", 12.9784, 77.6408),
    "jayanagar": ("Karnataka", 12.9250, 77.5938),
    "hebbal": ("Karnataka", 13.0358, 77.5970),
    "electronic city": ("Karnataka", 12.8452, 77.6602),

    # --- Tamil Nadu ---
    "chennai": ("Tamil Nadu", 13.0827, 80.2707),
    "madras": ("Tamil Nadu", 13.0827, 80.2707),
    "coimbatore": ("Tamil Nadu", 11.0168, 76.9558),
    "madurai": ("Tamil Nadu", 9.9252, 78.1198),
    "tiruchirappalli": ("Tamil Nadu", 10.7905, 78.7047),
    "trichy": ("Tamil Nadu", 10.7905, 78.7047),
    "salem": ("Tamil Nadu", 11.6643, 78.1460),
    "tirunelveli": ("Tamil Nadu", 8.7139, 77.7567),
    "erode": ("Tamil Nadu", 11.3410, 77.7172),
    "vellore": ("Tamil Nadu", 12.9165, 79.1325),
    "thoothukudi": ("Tamil Nadu", 8.7642, 78.1348),
    "tuticorin": ("Tamil Nadu", 8.7642, 78.1348),
    "nagercoil": ("Tamil Nadu", 8.1780, 77.4286),
    "kanyakumari": ("Tamil Nadu", 8.0883, 77.5385),
    "ooty": ("Tamil Nadu", 11.4064, 76.6932),
    "nilgiris": ("Tamil Nadu", 11.4064, 76.6932),
    "cuddalore": ("Tamil Nadu", 11.7480, 79.7714),
    "thanjavur": ("Tamil Nadu", 10.7870, 79.1378),
    "dindigul": ("Tamil Nadu", 10.3673, 77.9803),
    "kanchipuram": ("Tamil Nadu", 12.8342, 79.7036),
    "tambaram": ("Tamil Nadu", 12.9249, 80.1000),

    # --- Kerala ---
    "thiruvananthapuram": ("Kerala", 8.5241, 76.9366),
    "trivandrum": ("Kerala", 8.5241, 76.9366),
    "kochi": ("Kerala", 9.9312, 76.2673),
    "cochin": ("Kerala", 9.9312, 76.2673),
    "ernakulam": ("Kerala", 9.9816, 76.2999),
    "kozhikode": ("Kerala", 11.2588, 75.7804),
    "calicut": ("Kerala", 11.2588, 75.7804),
    "thrissur": ("Kerala", 10.5276, 76.2144),
    "kollam": ("Kerala", 8.8932, 76.6141),
    "alappuzha": ("Kerala", 9.4981, 76.3388),
    "alleppey": ("Kerala", 9.4981, 76.3388),
    "kottayam": ("Kerala", 9.5916, 76.5222),
    "palakkad": ("Kerala", 10.7867, 76.6548),
    "malappuram": ("Kerala", 11.0510, 76.0711),
    "kannur": ("Kerala", 11.8745, 75.3704),
    "kasaragod": ("Kerala", 12.4996, 74.9869),
    "wayanad": ("Kerala", 11.6854, 76.1320),
    "idukki": ("Kerala", 9.8497, 76.9704),
    "pathanamthitta": ("Kerala", 9.2648, 76.7870),
    "munnar": ("Kerala", 10.0889, 77.0595),

    # --- West Bengal ---
    "kolkata": ("West Bengal", 22.5726, 88.3639),
    "calcutta": ("West Bengal", 22.5726, 88.3639),
    "howrah": ("West Bengal", 22.5958, 88.2636),
    "durgapur": ("West Bengal", 23.5204, 87.3119),
    "asansol": ("West Bengal", 23.6739, 86.9524),
    "siliguri": ("West Bengal", 26.7271, 88.3953),
    "darjeeling": ("West Bengal", 27.0360, 88.2627),
    "malda": ("West Bengal", 25.0119, 88.1433),
    "kharagpur": ("West Bengal", 22.3460, 87.2320),
    "sundarbans": ("West Bengal", 21.9497, 88.9000),
    "digha": ("West Bengal", 21.6270, 87.5077),
    "salt lake": ("West Bengal", 22.5800, 88.4200),

    # --- Uttar Pradesh ---
    "lucknow": ("Uttar Pradesh", 26.8467, 80.9462),
    "kanpur": ("Uttar Pradesh", 26.4499, 80.3319),
    "varanasi": ("Uttar Pradesh", 25.3176, 82.9739),
    "banaras": ("Uttar Pradesh", 25.3176, 82.9739),
    "agra": ("Uttar Pradesh", 27.1767, 78.0081),
    "prayagraj": ("Uttar Pradesh", 25.4358, 81.8463),
    "allahabad": ("Uttar Pradesh", 25.4358, 81.8463),
    "meerut": ("Uttar Pradesh", 28.9845, 77.7064),
    "bareilly": ("Uttar Pradesh", 28.3670, 79.4304),
    "aligarh": ("Uttar Pradesh", 27.8974, 78.0880),
    "moradabad": ("Uttar Pradesh", 28.8386, 78.7733),
    "gorakhpur": ("Uttar Pradesh", 26.7606, 83.3732),
    "saharanpur": ("Uttar Pradesh", 29.9680, 77.5460),
    "jhansi": ("Uttar Pradesh", 25.4484, 78.5685),
    "mathura": ("Uttar Pradesh", 27.4924, 77.6737),
    "ayodhya": ("Uttar Pradesh", 26.7922, 82.1998),
    "firozabad": ("Uttar Pradesh", 27.1592, 78.3957),
    "muzaffarnagar": ("Uttar Pradesh", 29.4727, 77.7085),

    # --- Gujarat ---
    "ahmedabad": ("Gujarat", 23.0225, 72.5714),
    "surat": ("Gujarat", 21.1702, 72.8311),
    "vadodara": ("Gujarat", 22.3072, 73.1812),
    "baroda": ("Gujarat", 22.3072, 73.1812),
    "rajkot": ("Gujarat", 22.3039, 70.8022),
    "bhavnagar": ("Gujarat", 21.7645, 72.1519),
    "jamnagar": ("Gujarat", 22.4707, 70.0577),
    "gandhinagar": ("Gujarat", 23.2156, 72.6369),
    "junagadh": ("Gujarat", 21.5222, 70.4579),
    "bhuj": ("Gujarat", 23.2420, 69.6669),
    "kutch": ("Gujarat", 23.7337, 69.8597),
    "porbandar": ("Gujarat", 21.6417, 69.6293),
    "valsad": ("Gujarat", 20.5992, 72.9342),
    "navsari": ("Gujarat", 20.9467, 72.9520),
    "saurashtra": ("Gujarat", 22.0000, 70.8000),

    # --- Rajasthan ---
    "jaipur": ("Rajasthan", 26.9124, 75.7873),
    "jodhpur": ("Rajasthan", 26.2389, 73.0243),
    "udaipur": ("Rajasthan", 24.5854, 73.7125),
    "kota": ("Rajasthan", 25.2138, 75.8648),
    "bikaner": ("Rajasthan", 28.0229, 73.3119),
    "ajmer": ("Rajasthan", 26.4499, 74.6399),
    "alwar": ("Rajasthan", 27.5530, 76.6346),
    "bharatpur": ("Rajasthan", 27.2152, 77.4977),
    "jaisalmer": ("Rajasthan", 26.9157, 70.9083),
    "sikar": ("Rajasthan", 27.6094, 75.1399),
    "pali": ("Rajasthan", 25.7711, 73.3234),
    "mount abu": ("Rajasthan", 24.5925, 72.7156),

    # --- Telangana / Andhra Pradesh ---
    "hyderabad": ("Telangana", 17.3850, 78.4867),
    "secunderabad": ("Telangana", 17.4399, 78.4983),
    "warangal": ("Telangana", 17.9689, 79.5941),
    "nizamabad": ("Telangana", 18.6725, 78.0941),
    "karimnagar": ("Telangana", 18.4386, 79.1288),
    "khammam": ("Telangana", 17.2473, 80.1514),
    "gachibowli": ("Telangana", 17.4400, 78.3489),
    "hitec city": ("Telangana", 17.4435, 78.3772),
    "visakhapatnam": ("Andhra Pradesh", 17.6868, 83.2185),
    "vizag": ("Andhra Pradesh", 17.6868, 83.2185),
    "vijayawada": ("Andhra Pradesh", 16.5062, 80.6480),
    "guntur": ("Andhra Pradesh", 16.3067, 80.4365),
    "nellore": ("Andhra Pradesh", 14.4426, 79.9865),
    "tirupati": ("Andhra Pradesh", 13.6288, 79.4192),
    "kurnool": ("Andhra Pradesh", 15.8281, 78.0373),
    "rajahmundry": ("Andhra Pradesh", 17.0005, 81.8040),
    "kakinada": ("Andhra Pradesh", 16.9891, 82.2475),
    "anantapur": ("Andhra Pradesh", 14.6819, 77.6006),
    "amaravati": ("Andhra Pradesh", 16.5130, 80.5165),

    # --- Madhya Pradesh / Chhattisgarh ---
    "bhopal": ("Madhya Pradesh", 23.2599, 77.4126),
    "indore": ("Madhya Pradesh", 22.7196, 75.8577),
    "jabalpur": ("Madhya Pradesh", 23.1815, 79.9864),
    "gwalior": ("Madhya Pradesh", 26.2183, 78.1828),
    "ujjain": ("Madhya Pradesh", 23.1765, 75.7885),
    "sagar": ("Madhya Pradesh", 23.8388, 78.7378),
    "satna": ("Madhya Pradesh", 24.5854, 80.8322),
    "rewa": ("Madhya Pradesh", 24.5362, 81.2961),
    "ratlam": ("Madhya Pradesh", 23.3315, 75.0367),
    "raipur": ("Chhattisgarh", 21.2514, 81.6296),
    "bhilai": ("Chhattisgarh", 21.1938, 81.3509),
    "bilaspur": ("Chhattisgarh", 22.0797, 82.1409),
    "korba": ("Chhattisgarh", 22.3595, 82.7501),
    "bastar": ("Chhattisgarh", 19.1071, 81.9535),

    # --- Bihar / Jharkhand ---
    "patna": ("Bihar", 25.5941, 85.1376),
    "gaya": ("Bihar", 24.7914, 85.0002),
    "bhagalpur": ("Bihar", 25.2425, 86.9842),
    "muzaffarpur": ("Bihar", 26.1197, 85.3910),
    "darbhanga": ("Bihar", 26.1542, 85.8918),
    "purnia": ("Bihar", 25.7771, 87.4753),
    "ranchi": ("Jharkhand", 23.3441, 85.3096),
    "jamshedpur": ("Jharkhand", 22.8046, 86.2029),
    "dhanbad": ("Jharkhand", 23.7957, 86.4304),
    "bokaro": ("Jharkhand", 23.6693, 86.1511),
    "hazaribagh": ("Jharkhand", 23.9925, 85.3637),

    # --- Odisha ---
    "bhubaneswar": ("Odisha", 20.2961, 85.8245),
    "cuttack": ("Odisha", 20.4625, 85.8830),
    "rourkela": ("Odisha", 22.2604, 84.8536),
    "puri": ("Odisha", 19.8135, 85.8312),
    "sambalpur": ("Odisha", 21.4669, 83.9812),
    "balasore": ("Odisha", 21.4934, 86.9335),
    "berhampur": ("Odisha", 19.3150, 84.7941),
    "paradip": ("Odisha", 20.3167, 86.6167),

    # --- Punjab / Haryana / Himachal / J&K / Uttarakhand ---
    "chandigarh": ("Chandigarh", 30.7333, 76.7794),
    "amritsar": ("Punjab", 31.6340, 74.8723),
    "ludhiana": ("Punjab", 30.9010, 75.8573),
    "jalandhar": ("Punjab", 31.3260, 75.5762),
    "patiala": ("Punjab", 30.3398, 76.3869),
    "bathinda": ("Punjab", 30.2110, 74.9455),
    "mohali": ("Punjab", 30.7046, 76.7179),
    "pathankot": ("Punjab", 32.2643, 75.6421),
    "hisar": ("Haryana", 29.1492, 75.7217),
    "panipat": ("Haryana", 29.3909, 76.9635),
    "ambala": ("Haryana", 30.3782, 76.7767),
    "karnal": ("Haryana", 29.6857, 76.9905),
    "rohtak": ("Haryana", 28.8955, 76.6066),
    "shimla": ("Himachal Pradesh", 31.1048, 77.1734),
    "manali": ("Himachal Pradesh", 32.2432, 77.1892),
    "dharamshala": ("Himachal Pradesh", 32.2190, 76.3234),
    "kullu": ("Himachal Pradesh", 31.9578, 77.1092),
    "mandi": ("Himachal Pradesh", 31.7080, 76.9318),
    "solan": ("Himachal Pradesh", 30.9045, 77.0967),
    "kinnaur": ("Himachal Pradesh", 31.6000, 78.4000),
    "srinagar": ("Jammu and Kashmir", 34.0837, 74.7973),
    "jammu": ("Jammu and Kashmir", 32.7266, 74.8570),
    "anantnag": ("Jammu and Kashmir", 33.7311, 75.1487),
    "baramulla": ("Jammu and Kashmir", 34.1980, 74.3636),
    "gulmarg": ("Jammu and Kashmir", 34.0484, 74.3805),
    "pahalgam": ("Jammu and Kashmir", 34.0161, 75.3150),
    "leh": ("Ladakh", 34.1526, 77.5771),
    "kargil": ("Ladakh", 34.5539, 76.1349),
    "dehradun": ("Uttarakhand", 30.3165, 78.0322),
    "haridwar": ("Uttarakhand", 29.9457, 78.1642),
    "nainital": ("Uttarakhand", 29.3919, 79.4542),
    "mussoorie": ("Uttarakhand", 30.4598, 78.0644),
    "rishikesh": ("Uttarakhand", 30.0869, 78.2676),
    "haldwani": ("Uttarakhand", 29.2183, 79.5130),
    "chamoli": ("Uttarakhand", 30.4000, 79.3200),
    "uttarkashi": ("Uttarakhand", 30.7268, 78.4354),
    "kedarnath": ("Uttarakhand", 30.7346, 79.0669),
    "badrinath": ("Uttarakhand", 30.7433, 79.4938),
    "joshimath": ("Uttarakhand", 30.5550, 79.5645),

    # --- North East ---
    "guwahati": ("Assam", 26.1445, 91.7362),
    "dibrugarh": ("Assam", 27.4728, 94.9120),
    "silchar": ("Assam", 24.8333, 92.7789),
    "jorhat": ("Assam", 26.7509, 94.2037),
    "tezpur": ("Assam", 26.6528, 92.7926),
    "nagaon": ("Assam", 26.3464, 92.6840),
    "barpeta": ("Assam", 26.3220, 90.9756),
    "dhubri": ("Assam", 26.0207, 89.9779),
    "brahmaputra": ("Assam", 26.1445, 91.7362),
    "shillong": ("Meghalaya", 25.5788, 91.8933),
    "cherrapunji": ("Meghalaya", 25.3000, 91.7000),
    "mawsynram": ("Meghalaya", 25.2986, 91.5822),
    "imphal": ("Manipur", 24.8170, 93.9368),
    "aizawl": ("Mizoram", 23.7271, 92.7176),
    "kohima": ("Nagaland", 25.6751, 94.1086),
    "dimapur": ("Nagaland", 25.9063, 93.7276),
    "agartala": ("Tripura", 23.8315, 91.2868),
    "itanagar": ("Arunachal Pradesh", 27.0844, 93.6053),
    "tawang": ("Arunachal Pradesh", 27.5861, 91.8594),
    "gangtok": ("Sikkim", 27.3389, 88.6065),

    # --- Goa / UTs ---
    "panaji": ("Goa", 15.4909, 73.8278),
    "panjim": ("Goa", 15.4909, 73.8278),
    "goa": ("Goa", 15.2993, 74.1240),
    "margao": ("Goa", 15.2832, 73.9862),
    "vasco": ("Goa", 15.3860, 73.8157),
    "puducherry": ("Puducherry", 11.9416, 79.8083),
    "pondicherry": ("Puducherry", 11.9416, 79.8083),
    "port blair": ("Andaman and Nicobar Islands", 11.6234, 92.7265),
    "andaman": ("Andaman and Nicobar Islands", 11.7401, 92.6586),
    "nicobar": ("Andaman and Nicobar Islands", 7.0000, 93.7000),
    "lakshadweep": ("Lakshadweep", 10.5667, 72.6417),
    "kavaratti": ("Lakshadweep", 10.5669, 72.6420),
    "daman": ("Dadra and Nagar Haveli and Daman and Diu", 20.3974, 72.8328),
    "diu": ("Dadra and Nagar Haveli and Daman and Diu", 20.7144, 70.9874),
    "silvassa": ("Dadra and Nagar Haveli and Daman and Diu", 20.2738, 73.0140),
}
