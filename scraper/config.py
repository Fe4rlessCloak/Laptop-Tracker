"""Central configuration for the OLX scraper.

All tunable values live here so the CLI and runner can reference them without
hardcoding site-specific details in multiple places.
"""

# Base URL for OLX Pakistan.
BASE_URL = "https://www.olx.com.pk"

# Laptops category. The category slug + ID come from OLX's own URL scheme:
#   https://www.olx.com.pk/laptops-computers-accessories_c443/q-laptops
# The `_c443` suffix is the category ID for "Computers & Accessories".
LAPTOPS_CATEGORY_PATH = "laptops-computers-accessories_c443"

# Search query appended to the category path.
SEARCH_QUERY = "q-laptops"

# Sort parameter to request newest-first ordering. OLX's default sort surfaces
# old featured/relevance ads at the top; `sorting=desc-creation` orders normal
# (non-featured) ads by newest first. Featured ads may still be pushed to the
# top and break the ordering, so the time-window filter remains the primary gate.
SORT_PARAM = "sorting=desc-creation"

# City slugs as used in OLX URLs, e.g.:
#   https://www.olx.com.pk/islamabad_g4060615/laptops-computers-accessories_c443/q-laptops
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
