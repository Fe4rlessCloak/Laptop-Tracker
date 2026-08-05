"""Integration tests for the runner end-to-end flow with a mocked fetcher.

The stub fetcher is page-aware so we can exercise the pagination loop: it
returns different search HTML per ``?page=N``, letting us verify multi-page
capture, early-stop on duplicate, and early-stop on time-window exhaustion.
"""

import os

from scraper.fetcher import Fetcher
from scraper.runner import run
from scraper.storage import connect, count_listings, fetch_all

# Page 1: one fresh listing (2h ago) + one old listing (3 weeks ago).
PAGE1_HTML = """
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

# Page 2: another fresh listing (5h ago).
PAGE2_HTML = """
<html><body><ul>
  <li>
    <a href="https://www.olx.com.pk/item/laptop-core-i7-iid-333">
      <img src="https://images.olx.com.pk/thumbnails/3-400x300.jpeg" />
      <h6>Laptop Core i7</h6>
      <span>Rs 55,000</span>
      <span>F-8, Islamabad</span>
      <span>5 hours ago</span>
    </a>
  </li>
</ul></body></html>
"""

# Page 3: only an old listing (3 weeks ago) -> time-window exhaustion.
PAGE3_HTML = """
<html><body><ul>
  <li>
    <a href="https://www.olx.com.pk/item/very-old-laptop-iid-444">
      <img src="https://images.olx.com.pk/thumbnails/4-400x300.jpeg" />
      <h6>Very Old Laptop</h6>
      <span>Rs 3,000</span>
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
    """Returns canned HTML keyed by the requested page number."""

    def __init__(self):
        super().__init__(delay=0)

    def get(self, url):
        if "/item/" in url:
            return ITEM_HTML
        if "?page=2" in url:
            return PAGE2_HTML
        if "?page=3" in url:
            return PAGE3_HTML
        return PAGE1_HTML

    def sleep_between(self):
        pass


def test_run_paginates_across_pages(tmp_path):
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

    # Page 1 keeps iid-111 (2h ago); page 2 keeps iid-333 (5h ago); page 3 has
    # no fresh listings so the loop stops. Old listings (iid-222, iid-444) are
    # skipped.
    assert summary.fetched == 2
    assert summary.new == 2
    assert summary.skipped == 2

    conn = connect(db_path)
    assert count_listings(conn) == 2
    rows = fetch_all(conn)
    ids = {r["item_id"] for r in rows}
    assert ids == {"111", "333"}
    by_id = {r["item_id"]: r for r in rows}
    assert by_id["111"]["description"] == "Core i5 8th gen, 8GB RAM."
    assert by_id["111"]["image_urls"] == [
        "https://images.olx.com.pk/thumbnails/1-400x300.jpeg"
    ]
    conn.close()

    assert os.path.exists(os.path.join(export_dir, "listings.csv"))
    assert os.path.exists(os.path.join(export_dir, "listings.json"))


def test_run_does_not_early_stop_on_duplicate(tmp_path):
    """Featured ads break OLX's newest-first ordering, so a duplicate on an
    early page must NOT stop the loop — newer ads can still appear on later
    pages. This guards against the premature-stop bug."""
    db_path = str(tmp_path / "olx.db")

    # Page 1 has iid-111 (2h ago); page 2 has iid-999 (5h ago).
    page1_html = """
    <html><body><ul>
      <li><a href="https://www.olx.com.pk/item/laptop-core-i5-iid-111">
        <h6>Laptop Core i5</h6><span>Rs 39,000</span><span>2 hours ago</span>
      </a></li>
    </ul></body></html>
    """
    page2_html = """
    <html><body><ul>
      <li><a href="https://www.olx.com.pk/item/laptop-core-i7-iid-999">
        <h6>Laptop Core i7</h6><span>Rs 55,000</span><span>5 hours ago</span>
      </a></li>
    </ul></body></html>
    """

    class SinglePageFetcher(StubFetcher):
        """First run: only page 1 (iid-111) exists."""

        def get(self, url):
            if "/item/" in url:
                return ITEM_HTML
            return page1_html

    class TwoPageFetcher(StubFetcher):
        """Second run: page 1 (iid-111) AND page 2 (iid-999) exist."""

        def get(self, url):
            if "/item/" in url:
                return ITEM_HTML
            if "?page=2" in url:
                return page2_html
            return page1_html

    # First run stores iid-111 only (page 2's iid-999 is not yet present).
    run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        fetcher=SinglePageFetcher(),
    )

    # Second run: page 1's iid-111 is already stored. A naive early-stop would
    # halt here and never reach page 2's iid-999 (which is new). The correct
    # behavior is to keep paging until the time window is exhausted, capturing
    # iid-999.
    summary = run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        fetcher=TwoPageFetcher(),
    )

    assert summary.new == 1  # iid-999 is captured despite the duplicate on page 1
    conn = connect(db_path)
    assert count_listings(conn) == 2
    conn.close()


def test_run_early_stops_on_time_window_exhaustion(tmp_path):
    db_path = str(tmp_path / "olx.db")

    # A stub that returns only old listings on every page -> the loop stops on
    # the first page because nothing is within the window.
    class OldOnlyFetcher(StubFetcher):
        def get(self, url):
            if "/item/" in url:
                return ITEM_HTML
            return PAGE3_HTML

    summary = run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        fetcher=OldOnlyFetcher(),
    )

    assert summary.fetched == 0
    assert summary.skipped == 1
    conn = connect(db_path)
    assert count_listings(conn) == 0
    conn.close()
