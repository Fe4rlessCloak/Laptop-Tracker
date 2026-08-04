"""Integration test for the runner end-to-end flow with a mocked fetcher."""

import os

from scraper.fetcher import Fetcher
from scraper.runner import run
from scraper.storage import connect, count_listings, fetch_all

SEARCH_HTML = """
<html><body><ul>
  <li>
    <a href="https://www.olx.com.pk/item/laptop-core-i5-iid-111">
      <img src="https://images.olx.com.pk/thumbnails/1-400x300.jpeg" />
      <h6>Laptop Core i5</h6>
      <span>Rs 39,000</span>
      <span>Blue Area, Islamabad</span>
      <span>2 hours ago</span>
    </a>
  </li>
  <li>
    <a href="https://www.olx.com.pk/item/old-laptop-iid-222">
      <img src="https://images.olx.com.pk/thumbnails/2-400x300.jpeg" />
      <h6>Old Laptop</h6>
      <span>Rs 5,000</span>
      <span>Rawalpindi</span>
      <span>3 weeks ago</span>
    </a>
  </li>
</ul></body></html>
"""

ITEM_HTML = """
<html><body>
  <div class="_2961c394" aria-label="Description">
    <div class="_5eb397e5">Description</div>
    <div class="_7a99ad24"><span>Core i5 8th gen, 8GB RAM.</span></div>
  </div>
  <img src="https://images.olx.com.pk/thumbnails/1-400x300.jpeg" />
</body></html>
"""


class StubFetcher(Fetcher):
    """Returns canned HTML for any URL."""

    def __init__(self):
        super().__init__(delay=0)

    def get(self, url):
        if "/item/" in url:
            return ITEM_HTML
        return SEARCH_HTML

    def sleep_between(self):
        pass


def test_run_end_to_end(tmp_path):
    db_path = str(tmp_path / "olx.db")
    export_dir = str(tmp_path / "out")

    summary = run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        export=["csv", "json"],
        export_dir=export_dir,
        fetcher=StubFetcher(),
    )

    # Only the 2-hours-ago listing is within the 24h window; the 3-weeks-ago
    # one is filtered out.
    assert summary.fetched == 1
    assert summary.new == 1
    assert summary.skipped == 1

    conn = connect(db_path)
    assert count_listings(conn) == 1
    rows = fetch_all(conn)
    assert rows[0]["item_id"] == "111"
    assert rows[0]["description"] == "Core i5 8th gen, 8GB RAM."
    assert rows[0]["image_urls"] == [
        "https://images.olx.com.pk/thumbnails/1-400x300.jpeg"
    ]
    conn.close()

    assert os.path.exists(os.path.join(export_dir, "listings.csv"))
    assert os.path.exists(os.path.join(export_dir, "listings.json"))


def test_run_upserts_on_second_run(tmp_path):
    db_path = str(tmp_path / "olx.db")

    run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        fetcher=StubFetcher(),
    )
    summary = run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        fetcher=StubFetcher(),
    )

    # Second run updates the existing row rather than duplicating it.
    assert summary.new == 0
    assert summary.updated == 1
    conn = connect(db_path)
    assert count_listings(conn) == 1
    conn.close()
