"""
config.py
---------
Central configuration for the Onyx weather-data ingestion pipeline.
 
Nothing in here should require you to touch other files. If you want to
track a new hashtag, add a new city, or point Reddit at a new subreddit,
do it here.
 
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
# hashtag search isn't available (e.g. RSS, Reddit full-text search).
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
# Reddit
# ---------------------------------------------------------------------------
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "onyx-weather-pipeline/0.1 by hackathon-team")
 
REDDIT_SUBREDDITS = [
    "india", "IndiaSpeaks", "mumbai", "delhi", "bangalore", "chennai",
    "Kolkata", "pune", "Hyderabad", "Kerala", "indianweather", "IndiaWeather",
]
REDDIT_SEARCH_LIMIT = 50  # posts fetched per subreddit per run
 
# ---------------------------------------------------------------------------
# Bluesky (AT Protocol) - public search endpoint, no API key required for
# read-only public post search.
# ---------------------------------------------------------------------------
BLUESKY_PUBLIC_ENDPOINT = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
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
    "Chandigarh",
]
 
# ---------------------------------------------------------------------------
# Major Indian cities -> (state, latitude, longitude)
# Not exhaustive - covers state capitals + major metros so the demo has
# real coordinates to plot. Extend freely.
# ---------------------------------------------------------------------------
INDIAN_CITIES = {
    "mumbai": ("Maharashtra", 19.0760, 72.8777),
    "delhi": ("Delhi", 28.7041, 77.1025),
    "new delhi": ("Delhi", 28.6139, 77.2090),
    "bangalore": ("Karnataka", 12.9716, 77.5946),
    "bengaluru": ("Karnataka", 12.9716, 77.5946),
    "chennai": ("Tamil Nadu", 13.0827, 80.2707),
    "kolkata": ("West Bengal", 22.5726, 88.3639),
    "hyderabad": ("Telangana", 17.3850, 78.4867),
    "pune": ("Maharashtra", 18.5204, 73.8567),
    "ahmedabad": ("Gujarat", 23.0225, 72.5714),
    "surat": ("Gujarat", 21.1702, 72.8311),
    "jaipur": ("Rajasthan", 26.9124, 75.7873),
    "lucknow": ("Uttar Pradesh", 26.8467, 80.9462),
    "kanpur": ("Uttar Pradesh", 26.4499, 80.3319),
    "nagpur": ("Maharashtra", 21.1458, 79.0882),
    "patna": ("Bihar", 25.5941, 85.1376),
    "indore": ("Madhya Pradesh", 22.7196, 75.8577),
    "bhopal": ("Madhya Pradesh", 23.2599, 77.4126),
    "thiruvananthapuram": ("Kerala", 8.5241, 76.9366),
    "kochi": ("Kerala", 9.9312, 76.2673),
    "cochin": ("Kerala", 9.9312, 76.2673),
    "kozhikode": ("Kerala", 11.2588, 75.7804),
    "guwahati": ("Assam", 26.1445, 91.7362),
    "bhubaneswar": ("Odisha", 20.2961, 85.8245),
    "chandigarh": ("Chandigarh", 30.7333, 76.7794),
    "dehradun": ("Uttarakhand", 30.3165, 78.0322),
    "shimla": ("Himachal Pradesh", 31.1048, 77.1734),
    "raipur": ("Chhattisgarh", 21.2514, 81.6296),
    "ranchi": ("Jharkhand", 23.3441, 85.3096),
    "amritsar": ("Punjab", 31.6340, 74.8723),
    "ludhiana": ("Punjab", 30.9010, 75.8573),
    "vadodara": ("Gujarat", 22.3072, 73.1812),
    "coimbatore": ("Tamil Nadu", 11.0168, 76.9558),
    "madurai": ("Tamil Nadu", 9.9252, 78.1198),
    "visakhapatnam": ("Andhra Pradesh", 17.6868, 83.2185),
    "vizag": ("Andhra Pradesh", 17.6868, 83.2185),
    "varanasi": ("Uttar Pradesh", 25.3176, 82.9739),
    "agra": ("Uttar Pradesh", 27.1767, 78.0081),
    "nashik": ("Maharashtra", 19.9975, 73.7898),
    "jodhpur": ("Rajasthan", 26.2389, 73.0243),
    "gurugram": ("Haryana", 28.4595, 77.0266),
    "gurgaon": ("Haryana", 28.4595, 77.0266),
    "noida": ("Uttar Pradesh", 28.5355, 77.3910),
    "faridabad": ("Haryana", 28.4089, 77.3178),
    "srinagar": ("Jammu and Kashmir", 34.0837, 74.7973),
    "jammu": ("Jammu and Kashmir", 32.7266, 74.8570),
    "imphal": ("Manipur", 24.8170, 93.9368),
    "shillong": ("Meghalaya", 25.5788, 91.8933),
    "agartala": ("Tripura", 23.8315, 91.2868),
    "aizawl": ("Mizoram", 23.7271, 92.7176),
    "kohima": ("Nagaland", 25.6751, 94.1086),
    "itanagar": ("Arunachal Pradesh", 27.0844, 93.6053),
    "gangtok": ("Sikkim", 27.3389, 88.6065),
    "panaji": ("Goa", 15.4909, 73.8278),
    "goa": ("Goa", 15.2993, 74.1240),
}