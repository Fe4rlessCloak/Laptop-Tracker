"""Unit and integration tests for the read-only Web UI and API."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from scraper.monitoring import (
    ATTEMPT_OK,
    ATTEMPT_REQUEST_ERROR,
    ATTEMPT_TRANSIENT_HTTP,
    OUTCOME_STORED,
    PAGE_TYPE_DETAIL,
    PAGE_TYPE_SEARCH,
    RUN_COMPLETED,
    RUN_COMPLETED_WITH_FETCH_ERRORS,
    SOURCE_ARCHIVE,
    SOURCE_LIVE,
    connect as mon_connect,
    finish_run,
    reconcile_archive_discovery,
    record_discovery,
    record_observation,
    record_request_event,
    start_run,
)
from scraper.storage import connect as olx_connect, upsert_listing
from scraper.web import create_app, query_listings, query_performance


def _seed_listing(
    olx_conn,
    *,
    item_id: str,
    title: str,
    price: str = "Rs 50,000",
    price_numeric: float | None = 50000.0,
    city: str = "islamabad",
    description: str = "Clean laptop",
    scraped_at: str = "2026-10-05T10:00:00+00:00",
    seller_name: str = "Ali",
    item_url: str | None = None,
) -> None:
    upsert_listing(
        olx_conn,
        {
            "item_id": item_id,
            "title": title,
            "price": price,
            "price_numeric": price_numeric,
            "currency": "PKR",
            "location": city.title(),
            "city": city,
            "relative_time": "1 hour ago",
            "posted_at": None,
            "description": description,
            "image_urls": [],
            "item_url": item_url or f"https://www.olx.com.pk/item/{item_id}",
            "is_featured": False,
            "scraped_at": scraped_at,
            "seller_name": seller_name,
        },
    )


def test_bootstrap_missing_databases(tmp_path):
    app = create_app(
        db_path=str(tmp_path / "missing_olx.db"),
        monitoring_db_path=str(tmp_path / "missing_mon.db"),
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "olx_db_exists": False,
        "monitoring_db_exists": False,
    }

    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "has not been created yet" in r_home.text

    r_perf = client.get("/performance")
    assert r_perf.status_code == 200
    assert "not yet initialized" in r_perf.text
    assert "No data" in r_perf.text


def test_olx_db_without_monitoring_db_supports_all_mode(tmp_path):
    olx_path = str(tmp_path / "olx.db")
    olx_conn = olx_connect(olx_path)
    _seed_listing(olx_conn, item_id="101", title="ThinkPad X1")
    olx_conn.close()

    app = create_app(
        db_path=olx_path,
        monitoring_db_path=str(tmp_path / "missing_mon.db"),
    )
    client = TestClient(app)

    today_resp = client.get("/api/listings")
    assert today_resp.status_code == 200
    assert today_resp.json()["total"] == 0
    assert "not initialized yet" in today_resp.json()["bootstrap_note"]

    all_resp = client.get("/api/listings?mode=all")
    assert all_resp.status_code == 200
    assert all_resp.json()["total"] == 1
    assert all_resp.json()["items"][0]["item_id"] == "101"


def test_discovered_today_vs_seen_today_and_filters(tmp_path):
    olx_path = str(tmp_path / "olx.db")
    mon_path = str(tmp_path / "monitoring.db")
    olx_conn = olx_connect(olx_path)
    mon_conn = mon_connect(mon_path)

    # Current PKT date: 2026-10-05 (now_utc = 2026-10-05T12:00:00Z)
    now_utc = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

    # Item 1: discovered yesterday PKT (18:59Z Oct 4 = 23:59 PKT Oct 4), seen again today PKT.
    _seed_listing(
        olx_conn,
        item_id="old-seen-today",
        title="Dell Latitude 7490",
        price="Rs 65,000",
        price_numeric=65000.0,
        city="islamabad",
        description="16GB RAM SSD",
    )
    record_discovery(
        mon_conn, "old-seen-today", "2026-10-04T18:59:59+00:00", source=SOURCE_LIVE
    )
    record_observation(
        mon_conn, "old-seen-today", "2026-10-05T04:00:00+00:00", outcome=OUTCOME_STORED
    )

    # Item 2: discovered at PKT midnight (19:00Z Oct 4 = 00:00 PKT Oct 5).
    _seed_listing(
        olx_conn,
        item_id="new-today-isb",
        title="Lenovo ThinkPad T480",
        price="Rs 55,000",
        price_numeric=55000.0,
        city="islamabad",
        description="Core i5 8th gen",
    )
    record_discovery(
        mon_conn, "new-today-isb", "2026-10-04T19:00:00+00:00", source=SOURCE_LIVE
    )
    record_observation(
        mon_conn, "new-today-isb", "2026-10-04T19:00:00+00:00", outcome=OUTCOME_STORED
    )

    # Item 3: discovered today in Rawalpindi, unknown price.
    _seed_listing(
        olx_conn,
        item_id="new-today-rwp-noprice",
        title="HP EliteBook 840",
        price="Call for price",
        price_numeric=None,
        city="rawalpindi",
        description="Clean condition 100% original",
    )
    record_discovery(
        mon_conn, "new-today-rwp-noprice", "2026-10-05T08:00:00+00:00", source=SOURCE_LIVE
    )
    record_observation(
        mon_conn, "new-today-rwp-noprice", "2026-10-05T08:00:00+00:00", outcome=OUTCOME_STORED
    )

    # Item 4: baseline unknown discovery date, archived item, not seen today.
    _seed_listing(
        olx_conn,
        item_id="archive-unknown",
        title="MacBook Air M1",
        price="Rs 180,000",
        price_numeric=180000.0,
        city="islamabad",
    )
    reconcile_archive_discovery(mon_conn, "archive-unknown", "2026-09-10T10:00:00+00:00")

    # Item 5: baseline unknown discovery date (no timestamp).
    _seed_listing(
        olx_conn,
        item_id="unknown-date",
        title="Acer Aspire 5",
        price="Rs 40,000",
        price_numeric=40000.0,
        city="rawalpindi",
    )
    record_discovery(mon_conn, "unknown-date", None, source=SOURCE_LIVE)

    olx_conn.close()
    mon_conn.close()

    # Discovered today: only items 2 and 3.
    disc = query_listings(olx_path, mon_path, mode="discovered_today", now_utc=now_utc)
    assert disc["discovered_today"] == 2
    assert disc["unique_seen_today"] == 3
    assert disc["all_time_unique"] == 5
    assert disc["unknown_discovery_count"] == 1
    assert disc["has_archive_estimates"] is True
    assert {i["item_id"] for i in disc["items"]} == {
        "new-today-isb",
        "new-today-rwp-noprice",
    }

    # Seen today: items 1, 2, 3.
    seen = query_listings(olx_path, mon_path, mode="seen_today", now_utc=now_utc)
    assert {i["item_id"] for i in seen["items"]} == {
        "old-seen-today",
        "new-today-isb",
        "new-today-rwp-noprice",
    }

    # Numeric price filter excludes unknown prices.
    priced = query_listings(
        olx_path,
        mon_path,
        mode="discovered_today",
        min_price="50000",
        max_price="60000",
        now_utc=now_utc,
    )
    assert [i["item_id"] for i in priced["items"]] == ["new-today-isb"]

    # Keyword search matches description & escapes literal '%' safely.
    pct_search = query_listings(
        olx_path, mon_path, mode="all", q="100%", now_utc=now_utc
    )
    assert [i["item_id"] for i in pct_search["items"]] == ["new-today-rwp-noprice"]

    # City filter + sort price_asc.
    isb_sorted = query_listings(
        olx_path,
        mon_path,
        mode="all",
        city="islamabad",
        sort="price_asc",
        now_utc=now_utc,
    )
    assert [i["item_id"] for i in isb_sorted["items"]] == [
        "new-today-isb",
        "old-seen-today",
        "archive-unknown",
    ]

    # Discovery date range excludes unknown-date item.
    ranged = query_listings(
        olx_path,
        mon_path,
        mode="all",
        start_date="2026-09-01",
        end_date="2026-10-05",
        now_utc=now_utc,
    )
    assert ranged["total"] == 4
    assert "unknown-date" not in {i["item_id"] for i in ranged["items"]}


def test_web_validation_xss_escaping_and_readonly_methods(tmp_path):
    olx_path = str(tmp_path / "olx.db")
    mon_path = str(tmp_path / "monitoring.db")
    olx_conn = olx_connect(olx_path)
    mon_conn = mon_connect(mon_path)

    _seed_listing(
        olx_conn,
        item_id="xss-1",
        title='<script>alert("xss")</script>Laptop',
        description='<img onerror="alert(1)" />',
        seller_name="<b>Bad</b>",
        item_url="javascript:alert(1)",
    )
    record_discovery(mon_conn, "xss-1", "2026-10-05T08:00:00+00:00", source=SOURCE_LIVE)
    olx_conn.close()
    mon_conn.close()

    app = create_app(db_path=olx_path, monitoring_db_path=mon_path)
    client = TestClient(app)

    # Validation errors return 400 cleanly.
    bad_price = client.get("/api/listings?min_price=90000&max_price=10000")
    assert bad_price.status_code == 400
    assert "cannot exceed" in bad_price.json()["validation_error"]

    bad_date = client.get("/?mode=all&start_date=2026-10-10&end_date=2026-10-01")
    assert bad_date.status_code == 400
    assert "Start date cannot be after end date" in bad_date.text

    bad_window = client.get("/api/performance?window=invalid")
    assert bad_window.status_code == 400

    # HTML escapes dangerous tags and drops javascript: URLs.
    page = client.get("/?mode=all&q=%3Cscript%3E")
    assert page.status_code == 200
    assert '<script>alert("xss")</script>' not in page.text
    assert "&lt;script&gt;" in page.text
    assert "javascript:alert" not in page.text

    # Write HTTP methods are not permitted.
    assert client.post("/").status_code == 405
    assert client.post("/api/listings").status_code == 405


def test_performance_ui_and_api_with_1000_plus_samples_and_incomplete_run(tmp_path):
    olx_path = str(tmp_path / "olx.db")
    mon_path = str(tmp_path / "monitoring.db")
    olx_connect(olx_path).close()
    mon_conn = mon_connect(mon_path)

    now = datetime.now(timezone.utc)
    start_run(
        mon_conn,
        run_id="run-1",
        started_at=(now - timedelta(hours=30)).isoformat(),
    )
    # Seed 1000 detail events (1..1000 ms) + 1 recovered search retry.
    for i in range(1, 1001):
        mon_conn.execute(
            """
            INSERT INTO request_events
                (run_id, recorded_at, recorded_date, page_type, city,
                 attempt_number, status_code, outcome, is_final, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-1",
                (now - timedelta(hours=29)).isoformat(),
                "2026-10-04",
                PAGE_TYPE_DETAIL,
                "islamabad",
                1,
                200,
                ATTEMPT_OK,
                1,
                float(i),
            ),
        )
    mon_conn.commit()
    record_request_event(
        mon_conn,
        run_id="run-1",
        page_type=PAGE_TYPE_SEARCH,
        city="islamabad",
        attempt_number=1,
        status_code=503,
        outcome=ATTEMPT_TRANSIENT_HTTP,
        is_final=False,
        duration_ms=250.0,
        recorded_at=(now - timedelta(hours=29)).isoformat(),
    )
    record_request_event(
        mon_conn,
        run_id="run-1",
        page_type=PAGE_TYPE_SEARCH,
        city="islamabad",
        attempt_number=2,
        status_code=200,
        outcome=ATTEMPT_OK,
        is_final=True,
        duration_ms=120.0,
        recorded_at=(now - timedelta(hours=29)).isoformat(),
    )
    finish_run(
        mon_conn,
        "run-1",
        outcome=RUN_COMPLETED_WITH_FETCH_ERRORS,
        completed_at=(now - timedelta(hours=28)).isoformat(),
        duration_ms=45000.0,
        listings_seen=10,
        new_count=4,
        stored_count=10,
        error_count=1,
    )
    # Also simulate a crashed / incomplete newer run.
    start_run(
        mon_conn,
        run_id="run-crashed",
        started_at=(now - timedelta(hours=1)).isoformat(),
    )
    mon_conn.close()

    app = create_app(db_path=olx_path, monitoring_db_path=mon_path)
    client = TestClient(app)

    perf = client.get("/api/performance?window=all")
    assert perf.status_code == 200
    data = perf.json()
    assert data["is_stale"] is True
    assert data["by_page_type"]["detail"]["count"] == 1000
    assert data["by_page_type"]["detail"]["p99_ms"] == 990.01
    assert data["by_page_type"]["detail"]["p999_ms"] == 999.001
    assert data["by_page_type"]["search"]["retries"] == 1
    assert data["by_page_type"]["search"]["final_failures"] == 0
    assert data["recent_runs"][0]["effective_outcome"] == "incomplete"

    html_resp = client.get("/performance?window=all")
    assert html_resp.status_code == 200
    assert "Stale scraper warning" in html_resp.text
    assert "P99 (Slowest 1%)" in html_resp.text
    assert "P99.9 (Slowest 0.1%)" in html_resp.text
    assert "incomplete" in html_resp.text


def test_concurrent_wal_reads_while_writer_transaction_open(tmp_path):
    """Web UI read-only queries succeed against WAL monitoring.db even while
    a scraper writer connection is open."""
    olx_path = str(tmp_path / "olx.db")
    mon_path = str(tmp_path / "monitoring.db")

    olx_conn = olx_connect(olx_path)
    _seed_listing(olx_conn, item_id="wal-1", title="WAL Laptop")
    olx_conn.close()

    # Keep writer open in WAL mode with uncommitted/active state.
    writer = mon_connect(mon_path)
    now = datetime.now(timezone.utc)
    today_iso = now.isoformat()
    record_discovery(writer, "wal-1", today_iso, source=SOURCE_LIVE)
    record_observation(writer, "wal-1", today_iso, outcome=OUTCOME_STORED)
    start_run(writer, run_id="wal-run", started_at=today_iso)
    record_request_event(
        writer,
        run_id="wal-run",
        page_type=PAGE_TYPE_SEARCH,
        outcome=ATTEMPT_OK,
        duration_ms=55.0,
        recorded_at=today_iso,
    )

    try:
        app = create_app(db_path=olx_path, monitoring_db_path=mon_path)
        client = TestClient(app)
        resp = client.get("/api/listings?mode=discovered_today")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["item_id"] == "wal-1"

        perf = client.get("/api/performance?window=all")
        assert perf.status_code == 200
        assert perf.json()["overall"]["count"] == 1
        assert perf.json()["recent_runs"][0]["effective_outcome"] == "incomplete"
    finally:
        writer.close()
