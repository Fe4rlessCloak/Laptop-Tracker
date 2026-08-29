"""Central configuration for the OLX scraper.

All tunable values live here so the CLI and runner can reference them without
hardcoding site-specific details in multiple places.
"""

# Base URL for OLX Pakistan.
BASE_URL = "https://www.olx.com.pk"

# OLX category paths, keyed by short slug. The category slug + ID come from
# OLX's own URL scheme, e.g.:
#   https://www.olx.com.pk/laptops_c708203/q-laptop
# The `_c<id>` suffix is OLX's internal category ID. Using a dict (not a single
# constant) makes the lookup extensible: a future scraper for a different
# category only needs a new entry here, plus a new --category CLI value.
CATEGORIES = {
    "laptops": "laptops_c708203",
}

# Search query appended to the category path.
SEARCH_QUERY = "q-laptop"

# Sort parameter to request newest-first ordering. OLX's default sort surfaces
# old featured/relevance ads at the top; `sorting=desc-creation` orders normal
# (non-featured) ads by newest first. Featured ads may still be pushed to the
# top and break the ordering, so the time-window filter remains the primary gate.
SORT_PARAM = "sorting=desc-creation"

# City slugs as used in OLX URLs, e.g.:
#   https://www.olx.com.pk/islamabad_g4060615/laptops_c708203/q-laptop
# The `_g<id>` suffix is the geographic region ID.
DEFAULT_CITIES = {
    "islamabad": "islamabad_g4060615",
    "rawalpindi": "rawalpindi_g4060681",
}

# Default time window (in hours) to look back when filtering listings.
DEFAULT_HOURS = 24

# Safety cap on the number of search pages fetched per city. The pagination
# loop normally stops earlier (time-window exhaustion or first duplicate), but
# this guarantees termination even if OLX behaves unexpectedly. At ~50 ads/page
# this covers ~1000 ads, far more than a 24h window needs.
MAX_PAGES = 20

# Default delay (seconds) between HTTP requests to stay polite to the site.
DEFAULT_DELAY = 2.0

# Realistic browser User-Agent to reduce the chance of being blocked.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Retry/backoff settings for transient network failures.
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds, multiplied by attempt number

# Default output paths (relative to the project root).
DEFAULT_DB_PATH = "data/olx.db"
DEFAULT_EXPORT_DIR = "data"
