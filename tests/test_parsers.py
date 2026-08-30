"""Unit tests for the OLX HTML parsers."""

from scraper.parsers import (
    is_within_hours,
    normalize_price,
    parse_item_detail,
    parse_relative_time,
    parse_search_results,
)


# ---------------------------------------------------------------------------
# Price normalization
# ---------------------------------------------------------------------------

def test_normalize_price_plain():
    assert normalize_price("Rs 39,000") == 39000.0
    assert normalize_price("Rs 2,200") == 2200.0


def test_normalize_price_lac():
    assert normalize_price("Rs 1.40 Lac") == 140000.0
    assert normalize_price("Rs 10.40 Lacs") == 1040000.0


def test_normalize_price_crore():
    assert normalize_price("Rs 1.5 Crore") == 15000000.0


def test_normalize_price_none():
    assert normalize_price(None) is None
    assert normalize_price("") is None
    assert normalize_price("Free") is None


# ---------------------------------------------------------------------------
# Relative time parsing
# ---------------------------------------------------------------------------

def test_parse_relative_time_hours():
    posted = parse_relative_time("2 hours ago")
    assert posted is not None
    age = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - posted)
    assert 1.5 * 3600 <= age.total_seconds() <= 2.5 * 3600


def test_parse_relative_time_days():
    posted = parse_relative_time("3 days ago")
    assert posted is not None


def test_parse_relative_time_invalid():
    assert parse_relative_time("no time here") is None
    assert parse_relative_time(None) is None


def test_is_within_hours():
    assert is_within_hours("1 hour ago", 24) is True
    assert is_within_hours("1 day ago", 24) is True
    assert is_within_hours("3 days ago", 24) is False
    # Unknown age fails open (kept).
    assert is_within_hours("unknown", 24) is True


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------

SEARCH_HTML = """
<html><body><ul>
  <li>
    <a href="https://www.olx.com.pk/item/laptop-core-i5-iid-1077082458">
      <img src="https://images.olx.com.pk/thumbnails/1-400x300.jpeg" />
      <h6>Laptop Core i5 Dell Hp Lenovo</h6>
      <span>Rs 39,000</span>
      <span>Allama Iqbal Town - Huma Block, Lahore</span>
      <span>1 day ago</span>
    </a>
  </li>
  <li>
    <a href="https://www.olx.com.pk/item/macbook-air-m1-iid-1065072085">
      <img src="https://images.olx.com.pk/thumbnails/2-400x300.jpeg" />
      <h6>MacBook Air M1 Lush Condition</h6>
      <span>Rs 1.40 Lac</span>
      <span>Blue Area, Islamabad</span>
      <span>2 hours ago</span>
    </a>
  </li>
</ul></body></html>
"""


def test_parse_search_results_extracts_listings():
    listings = parse_search_results(SEARCH_HTML, "islamabad")
    assert len(listings) == 2

    first = listings[0]
    assert first["item_id"] == "1077082458"
    assert first["title"] == "Laptop Core i5 Dell Hp Lenovo"
    assert first["price"] == "Rs 39,000"
    assert first["price_numeric"] == 39000.0
    assert first["city"] == "islamabad"
    assert first["relative_time"] == "1 day ago"
    assert first["image_urls"] == ["https://images.olx.com.pk/thumbnails/1-400x300.jpeg"]
    assert first["item_url"].endswith("-iid-1077082458")


def test_parse_search_results_lac_price():
    listings = parse_search_results(SEARCH_HTML, "islamabad")
    second = listings[1]
    assert second["price_numeric"] == 140000.0


def test_parse_search_results_dedupes():
    # Two anchors pointing at the same item should yield one listing.
    html = """
    <ul>
      <li>
        <a href="https://www.olx.com.pk/item/x-iid-1"><h6>Title</h6></a>
        <a href="https://www.olx.com.pk/item/x-iid-1"><h6>Title</h6></a>
      </li>
    </ul>
    """
    listings = parse_search_results(html, "islamabad")
    assert len(listings) == 1


# ---------------------------------------------------------------------------
# Item detail parsing
# ---------------------------------------------------------------------------

ITEM_HTML = """
<html><body>
  <div class="_2961c394" aria-label="Description">
    <div class="_5eb397e5">Description</div>
    <div class="_7a99ad24"><span>Core i5 8th gen, 8GB RAM, 256GB SSD. Fully working.</span></div>
  </div>
  <img src="https://images.olx.com.pk/thumbnails/a.jpeg" />
  <img src="https://images.olx.com.pk/thumbnails/b.jpeg" />
</body></html>
"""


def test_parse_item_detail_description():
    listing = {"item_id": "1", "description": None, "image_urls": []}
    result = parse_item_detail(ITEM_HTML, listing)
    assert "Core i5 8th gen" in result["description"]


def test_parse_item_detail_images():
    listing = {"item_id": "1", "description": None, "image_urls": []}
    result = parse_item_detail(ITEM_HTML, listing)
    assert len(result["image_urls"]) == 2


# ---------------------------------------------------------------------------
# Seller name extraction
# ---------------------------------------------------------------------------

ITEM_HTML_WITH_JSONLD = """
<html><body>
  <div class="_2961c394" aria-label="Description">
    <div class="_7a99ad24"><span>A used laptop in great condition.</span></div>
  </div>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "Laptop Core i5",
    "seller": {"@type": "Person", "name": "Ayesha Khan"},
    "description": "..."
  }
  </script>
</body></html>
"""


ITEM_HTML_WITH_POSTED_BY = """
<html><body>
  <div class="_2961c394" aria-label="Description">
    <div class="_7a99ad24"><span>A used laptop in great condition.</span></div>
  </div>
  <div>
    <span>Posted by</span>
    <div><span class="a1c1940e b7af14b4">Bilal Ahmed </span></div>
  </div>
</body></html>
"""


ITEM_HTML_NO_SELLER = """
<html><body>
  <div class="_2961c394" aria-label="Description">
    <div class="_7a99ad24"><span>A used laptop in great condition.</span></div>
  </div>
</body></html>
"""


ITEM_HTML_BROKEN_JSONLD = """
<html><body>
  <script type="application/ld+json">
  {"@type": "Product", "name": "Laptop", "seller": {this is not valid json
  </script>
  <div>
    <span>Posted by</span>
    <div><span>Sara Malik</span></div>
  </div>
</body></html>
"""


def test_parse_item_detail_seller_name_from_jsonld():
    listing = {"item_id": "1"}
    result = parse_item_detail(ITEM_HTML_WITH_JSONLD, listing)
    assert result["seller_name"] == "Ayesha Khan"


def test_parse_item_detail_seller_name_from_posted_by():
    listing = {"item_id": "1"}
    result = parse_item_detail(ITEM_HTML_WITH_POSTED_BY, listing)
    # Falls back to "Posted by <name>" when JSON-LD is absent.
    assert result["seller_name"] == "Bilal Ahmed"


def test_parse_item_detail_seller_name_absent():
    listing = {"item_id": "1"}
    result = parse_item_detail(ITEM_HTML_NO_SELLER, listing)
    assert result["seller_name"] is None


def test_parse_item_detail_seller_name_robust_to_bad_jsonld():
    """Malformed JSON-LD must not crash; fall back to the visible label."""
    listing = {"item_id": "1"}
    result = parse_item_detail(ITEM_HTML_BROKEN_JSONLD, listing)
    assert result["seller_name"] == "Sara Malik"


def test_parse_item_detail_seller_name_preserves_existing_value():
    """If the listing already has a seller_name, a re-scrape that fails to
    extract one must not clobber the existing value."""
    listing = {"item_id": "1", "seller_name": "Hassan Raza"}
    result = parse_item_detail(ITEM_HTML_NO_SELLER, listing)
    assert result["seller_name"] == "Hassan Raza"
