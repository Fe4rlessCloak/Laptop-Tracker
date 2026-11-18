"""Integration tests for the runner end-to-end flow with a mocked fetcher.

The stub fetcher is page-aware so we can exercise the pagination loop: it
returns different search HTML per ``?page=N``, letting us verify multi-page
capture, early-stop on duplicate, and early-stop on time-window exhaustion.
"""

import os
import sqlite3
from datetime import date

import pytest

from scraper import config
from scraper.fetcher import FetchBlocked, Fetcher
from scraper.monitoring import (
    OUTCOME_FAILED,
    OUTCOME_STORED,
    RUN_COMPLETED,
    RUN_COMPLETED_WITH_FETCH_ERRORS,
    RUN_FAILED,
    connect as mon_connect,
    count_observations,
    count_unique_listings,
    get_performance_summary,
)
from scraper.runner import build_search_url, run
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

    today_iso = date.today().isoformat()
    assert os.path.exists(os.path.join(export_dir, f"listings-{today_iso}.csv"))
    assert os.path.exists(os.path.join(export_dir, f"listings-{today_iso}.json"))


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


def test_build_search_url_uses_laptops_c708203():
    """The search base must be the Laptops-only category (c708203), not the
    broader Computers & Accessories (c443), so non-laptop items are excluded
    at the source rather than after fetch."""
    url = build_search_url("islamabad_g4060615", 1)

    assert "laptops_c708203" in url
    assert "page=1" in url
    assert "sorting=desc-creation" in url
    # Regression guard: the old broader category must not reappear.
    assert "c443" not in url
    assert "laptops-computers-accessories" not in url


def test_build_search_url_unknown_category_raises():
    with pytest.raises(KeyError):
        build_search_url("islamabad_g4060615", 1, category="phones")


def test_build_search_url_round_trips_every_documented_category():
    """Every key in CATEGORIES must produce a valid URL (defense against
    config drift — if a new category is added with a typo, this catches it)."""
    for category in config.CATEGORIES:
        url = build_search_url("islamabad_g4060615", 1, category=category)
        assert config.CATEGORIES[category] in url
        assert "page=1" in url
        assert "sorting=desc-creation" in url


def test_run_records_monitoring_telemetry_across_repeat_runs(tmp_path):
    """Two runs with a repeated listing, a recovered detail retry, and an
    exhausted detail fetch record exact discoveries, observations, runs, and
    request_events without altering olx.db."""

    class Resp:
        def __init__(self, status_code, text="", headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

    class ScriptedSession:
        def __init__(self, responses):
            self.responses = list(responses)
            self.headers = {}

        def get(self, url, timeout=None):
            return self.responses.pop(0)

    db_path = str(tmp_path / "olx.db")
    mon_path = str(tmp_path / "monitoring.db")

    # Run 1: page1 (1 fresh item iid-111), detail retries 503->200, page2 (old).
    session1 = ScriptedSession(
        [
            Resp(200, PAGE1_HTML),
            Resp(503, ""),
            Resp(200, ITEM_HTML),
            Resp(200, PAGE3_HTML),
        ]
    )
    fetcher1 = Fetcher(delay=0, max_retries=2, backoff=0, session=session1)
    s1 = run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        monitoring_db_path=mon_path,
        fetcher=fetcher1,
    )
    assert s1.new == 1
    assert s1.errors == 0

    # Run 2: same iid-111 appears again, detail fetch exhausts retries (404),
    # partial listing is still stored, run finishes completed-with-fetch-errors.
    session2 = ScriptedSession(
        [
            Resp(200, PAGE1_HTML),
            Resp(404, ""),
            Resp(200, PAGE3_HTML),
        ]
    )
    fetcher2 = Fetcher(delay=0, max_retries=2, backoff=0, session=session2)
    s2 = run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        monitoring_db_path=mon_path,
        fetcher=fetcher2,
    )
    assert s2.updated == 1
    assert s2.errors == 1

    mon = mon_connect(mon_path)
    assert count_unique_listings(mon) == 1
    assert count_observations(mon, outcome=OUTCOME_STORED) == 2

    perf = get_performance_summary(mon, window="all")
    assert len(perf["recent_runs"]) == 2
    assert perf["recent_runs"][0]["outcome"] == RUN_COMPLETED_WITH_FETCH_ERRORS
    assert perf["recent_runs"][1]["outcome"] == RUN_COMPLETED
    assert perf["overall"]["total_attempts"] == 7
    assert perf["overall"]["failed_attempts"] == 2
    assert perf["overall"]["logical_fetches"] == 6
    assert perf["overall"]["final_failures"] == 1
    assert perf["overall"]["retries"] == 1
    mon.close()


def test_run_records_failed_observation_and_run_on_storage_error(
    tmp_path, monkeypatch
):
    db_path = str(tmp_path / "olx.db")
    mon_path = str(tmp_path / "monitoring.db")

    def boom_upsert(_conn, _listing):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr("scraper.runner.upsert_listing", boom_upsert)

    with pytest.raises(sqlite3.OperationalError):
        run(
            cities={"islamabad": "islamabad_g4060615"},
            hours=24,
            db_path=db_path,
            monitoring_db_path=mon_path,
            fetcher=StubFetcher(),
        )

    mon = mon_connect(mon_path)
    assert count_observations(mon, outcome=OUTCOME_FAILED) == 1
    perf = get_performance_summary(mon, window="all")
    assert perf["recent_runs"][0]["outcome"] == RUN_FAILED
    mon.close()


def test_blocked_fetch_aborts_run_and_records_failure(tmp_path):
    db_path = str(tmp_path / "olx.db")
    mon_path = str(tmp_path / "monitoring.db")

    class BlockedFetcher(StubFetcher):
        def get(self, url):
            raise FetchBlocked("HTTP 503 with Retry-After 3600s")

    with pytest.raises(FetchBlocked):
        run(
            cities={
                "islamabad": "islamabad_g4060615",
                "rawalpindi": "rawalpindi_g4060681",
            },
            hours=24,
            db_path=db_path,
            monitoring_db_path=mon_path,
            fetcher=BlockedFetcher(),
        )

    conn = connect(db_path)
    assert count_listings(conn) == 0
    conn.close()

    mon = mon_connect(mon_path)
    assert count_unique_listings(mon) == 0
    perf = get_performance_summary(mon, window="all")
    assert perf["recent_runs"][0]["outcome"] == RUN_FAILED
    mon.close()


def test_monitoring_failure_does_not_abort_listing_ingestion(tmp_path):
    db_path = str(tmp_path / "olx.db")
    # Point monitoring_db_path at a file inside a path blocked by a regular file.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    bad_mon_path = str(blocker / "monitoring.db")

    summary = run(
        cities={"islamabad": "islamabad_g4060615"},
        hours=24,
        db_path=db_path,
        monitoring_db_path=bad_mon_path,
        fetcher=StubFetcher(),
    )
    assert summary.new == 2
    conn = connect(db_path)
    assert count_listings(conn) == 2
    conn.close()
