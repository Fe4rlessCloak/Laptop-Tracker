"""Unit tests for the isolated monitoring storage layer.

All fixtures are synthetic. Production databases and daily exports are never
read, copied, or embedded here (see SPECS.md monitoring specification).
"""

import json
import sqlite3

import pytest

from scraper.monitoring import (
    OUTCOME_FAILED,
    OUTCOME_STORED,
    PKT_FIXED_TZ,
    RUN_COMPLETED,
    SOURCE_ARCHIVE,
    SOURCE_LIVE,
    SOURCE_UNKNOWN,
    connect,
    count_discoveries,
    count_observations,
    count_unique_listings,
    finish_run,
    get_counter,
    get_counters,
    import_archive,
    increment_counter,
    list_incomplete_runs,
    main,
    parse_timestamp,
    reconcile_archive_discovery,
    record_discovery,
    record_observation,
    resolve_karachi_tz,
    start_run,
    to_karachi_date,
)


@pytest.fixture()
def db(tmp_path):
    conn = connect(str(tmp_path / "monitoring.db"))
    yield conn
    conn.close()


def _write_json(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_connect_creates_monitoring_tables(db):
    names = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "discoveries",
        "observations",
        "runs",
        "archive_imports",
        "counters",
        "schema_meta",
    } <= names


def test_monitoring_db_is_isolated_from_listing_table(db):
    """The monitoring database must not contain the listing table."""
    names = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "listings" not in names


def test_migrate_adds_discovered_date_to_legacy_db(tmp_path):
    """A monitoring DB created before ``discovered_date`` existed is upgraded
    in place without losing rows."""
    path = str(tmp_path / "legacy-monitoring.db")
    legacy = sqlite3.connect(path)
    legacy.execute(
        """
        CREATE TABLE discoveries (
            item_id          TEXT PRIMARY KEY,
            discovered_at    TEXT,
            discovery_source TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        )
        """
    )
    legacy.execute(
        "INSERT INTO discoveries VALUES (?, ?, ?, ?)",
        ("old-1", "2026-01-01T00:00:00+00:00", "archive", "2026-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()

    conn = connect(path)
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(discoveries)")
    }
    assert "discovered_date" in columns
    assert count_unique_listings(conn) == 1
    conn.close()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def test_parse_timestamp_accepts_z_suffix():
    assert (
        parse_timestamp("2026-10-04T20:00:00Z").isoformat()
        == "2026-10-04T20:00:00+00:00"
    )


def test_to_karachi_date_rolls_over_at_midnight():
    # 20:00 UTC is 01:00 the next day in Karachi (UTC+5).
    assert to_karachi_date("2026-10-04T20:00:00+00:00") == "2026-10-05"
    assert to_karachi_date("2026-10-04T18:59:59+00:00") == "2026-10-04"


def test_to_karachi_date_rejects_garbage():
    with pytest.raises(ValueError):
        to_karachi_date("not-a-date")


def test_resolve_karachi_tz_falls_back_on_missing_tzdata(monkeypatch):
    def missing_zone(_name):
        raise KeyError("Asia/Karachi")

    assert resolve_karachi_tz(zoneinfo_cls=missing_zone) == PKT_FIXED_TZ

    real_import = __import__

    def no_zoneinfo(name, *args, **kwargs):
        if name == "zoneinfo":
            raise ImportError("No module named 'zoneinfo'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_zoneinfo)
    assert resolve_karachi_tz() == PKT_FIXED_TZ


def test_karachi_fallback_midnight_boundaries_match_zoneinfo(monkeypatch, db):
    from zoneinfo import ZoneInfo

    iana_tz = ZoneInfo("Asia/Karachi")
    # 18:59:59Z is 23:59:59 PKT; 19:00:00Z is 00:00:00 next PKT day.
    before_midnight = "2026-10-04T18:59:59+00:00"
    at_midnight = "2026-10-04T19:00:00+00:00"

    assert to_karachi_date(before_midnight, tz=iana_tz) == "2026-10-04"
    assert to_karachi_date(at_midnight, tz=iana_tz) == "2026-10-05"

    monkeypatch.setattr("scraper.monitoring.KARACHI_TZ", PKT_FIXED_TZ)
    assert to_karachi_date(before_midnight) == "2026-10-04"
    assert to_karachi_date(at_midnight) == "2026-10-05"

    record_discovery(db, "A1", before_midnight)
    record_discovery(db, "A2", at_midnight)
    record_observation(db, "A1", before_midnight)
    record_observation(db, "A2", at_midnight)

    assert count_discoveries(db, start_date="2026-10-04", end_date="2026-10-05") == 1
    assert count_discoveries(db, start_date="2026-10-05", end_date="2026-10-06") == 1
    assert count_observations(db, start_date="2026-10-04", end_date="2026-10-05") == 1
    assert count_observations(db, start_date="2026-10-05", end_date="2026-10-06") == 1


# ---------------------------------------------------------------------------
# Discovery records
# ---------------------------------------------------------------------------


def test_record_discovery_inserts_and_is_idempotent(db):
    assert record_discovery(db, "A1", "2026-10-04T10:00:00+00:00") is True
    # Replaying the same timestamp changes nothing.
    assert record_discovery(db, "A1", "2026-10-04T10:00:00+00:00") is False
    assert count_unique_listings(db) == 1


def test_record_discovery_lowers_archive_estimate(db):
    """Permitted archive reconciliation replaces an archive estimate with an
    *earlier* archive time idempotently."""
    assert (
        record_discovery(
            db, "A1", "2026-08-30T10:00:00+00:00", source=SOURCE_ARCHIVE
        )
        is True
    )
    assert (
        reconcile_archive_discovery(db, "A1", "2026-08-29T10:00:00+00:00")
        is True
    )
    # Replaying the same archive estimate is idempotent.
    assert (
        reconcile_archive_discovery(db, "A1", "2026-08-29T10:00:00+00:00")
        is False
    )
    row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='A1'"
    ).fetchone()
    assert row["discovered_at"] == "2026-08-29T10:00:00+00:00"
    assert row["discovery_source"] == SOURCE_ARCHIVE


def test_live_discovery_is_immutable_against_earlier_live_or_archive(db):
    assert record_discovery(db, "A1", "2026-10-04T10:00:00+00:00", source=SOURCE_LIVE) is True
    assert record_discovery(db, "A1", "2026-10-01T10:00:00+00:00", source=SOURCE_LIVE) is False
    assert reconcile_archive_discovery(db, "A1", "2026-08-30T10:00:00+00:00") is False
    row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='A1'"
    ).fetchone()
    assert row["discovered_at"] == "2026-10-04T10:00:00+00:00"
    assert row["discovery_source"] == SOURCE_LIVE


def test_later_archive_does_not_overwrite_earlier_archive_estimate(db):
    record_discovery(db, "A1", "2026-08-29T10:00:00+00:00", source=SOURCE_ARCHIVE)
    assert reconcile_archive_discovery(db, "A1", "2026-08-30T10:00:00+00:00") is False
    row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='A1'"
    ).fetchone()
    assert row["discovered_at"] == "2026-08-29T10:00:00+00:00"
    assert row["discovery_source"] == SOURCE_ARCHIVE


def test_unknown_baseline_not_recategorized_by_live_but_reconciled_by_archive(db):
    assert record_discovery(db, "base-1", None, source=SOURCE_LIVE) is True
    # Repeat live ingestion must not mark an unknown baseline as newly discovered.
    assert record_discovery(db, "base-1", "2026-10-05T10:00:00+00:00", source=SOURCE_LIVE) is False
    row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='base-1'"
    ).fetchone()
    assert row["discovered_at"] is None
    assert row["discovery_source"] == SOURCE_UNKNOWN
    assert count_discoveries(db, start_date="2026-10-05", end_date="2026-10-06") == 0

    # A retained archive with a valid scrape timestamp may provide the estimate.
    assert reconcile_archive_discovery(db, "base-1", "2026-08-30T10:00:00+00:00") is True
    row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='base-1'"
    ).fetchone()
    assert row["discovered_at"] == "2026-08-30T10:00:00+00:00"
    assert row["discovery_source"] == SOURCE_ARCHIVE


def test_record_discovery_never_moves_later(db):
    record_discovery(db, "A1", "2026-08-29T10:00:00+00:00")
    assert record_discovery(db, "A1", "2026-08-30T10:00:00+00:00") is False
    row = db.execute(
        "SELECT discovered_at FROM discoveries WHERE item_id='A1'"
    ).fetchone()
    assert row["discovered_at"] == "2026-08-29T10:00:00+00:00"


def test_unknown_discovery_date_counts_all_time_only(db):
    assert record_discovery(db, "base-1", None, source=SOURCE_LIVE) is True
    row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='base-1'"
    ).fetchone()
    assert row["discovered_at"] is None
    assert row["discovery_source"] == "unknown"
    # Included in all-time totals ...
    assert count_unique_listings(db) == 1
    assert count_discoveries(db) == 1
    # ... but excluded from a bounded date range.
    assert count_discoveries(db, start_date="2020-01-01") == 0


def test_record_discovery_ignores_empty_item_id(db):
    assert record_discovery(db, "", "2026-10-04T10:00:00+00:00") is False
    assert count_unique_listings(db) == 0


# ---------------------------------------------------------------------------
# Observation records
# ---------------------------------------------------------------------------


def test_repeated_observations_increment_observations_not_discoveries(db):
    record_discovery(db, "A1", "2026-10-04T10:00:00+00:00")
    record_observation(db, "A1", "2026-10-04T10:00:00+00:00", run_id="r1")
    record_observation(db, "A1", "2026-10-04T12:00:00+00:00", run_id="r2")
    assert count_unique_listings(db) == 1
    assert count_observations(db) == 2


def test_observation_outcomes_counted_separately(db):
    record_observation(
        db, "A1", "2026-10-04T10:00:00+00:00", outcome=OUTCOME_STORED
    )
    record_observation(
        db, "A2", "2026-10-04T10:00:00+00:00", outcome=OUTCOME_FAILED
    )
    assert count_observations(db) == 2
    assert count_observations(db, outcome=OUTCOME_STORED) == 1
    assert count_observations(db, outcome=OUTCOME_FAILED) == 1


def test_observation_idempotency_key_deduplicates(db):
    first = record_observation(
        db,
        "A1",
        "2026-08-30T10:00:00+00:00",
        source=SOURCE_ARCHIVE,
        idempotency_key="archive:A1:2026-08-30T10:00:00+00:00",
    )
    second = record_observation(
        db,
        "A1",
        "2026-08-30T10:00:00+00:00",
        source=SOURCE_ARCHIVE,
        idempotency_key="archive:A1:2026-08-30T10:00:00+00:00",
    )
    assert first is not None
    assert second is None
    assert count_observations(db) == 1


def test_invalid_observation_outcome_raises_without_losing_prior_rows(db):
    record_observation(db, "A1", "2026-10-04T10:00:00+00:00")
    with pytest.raises(ValueError):
        record_observation(db, "A2", "2026-10-04T10:00:00+00:00", outcome="bogus")
    assert count_observations(db) == 1


def test_counts_use_karachi_calendar_dates(db):
    record_observation(db, "A1", "2026-10-04T18:00:00+00:00")  # 23:00, 10-04
    record_observation(db, "A2", "2026-10-04T20:00:00+00:00")  # 01:00, 10-05
    assert count_observations(db, start_date="2026-10-04", end_date="2026-10-05") == 1
    assert count_observations(db, start_date="2026-10-05", end_date="2026-10-06") == 1


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


def test_run_lifecycle_and_incomplete_detection(db):
    run_id = start_run(db, run_id="run-1", started_at="2026-10-04T09:00:00+00:00")
    assert run_id == "run-1"
    # Started but not finished: visible as incomplete.
    assert [r["run_id"] for r in list_incomplete_runs(db)] == ["run-1"]

    finish_run(
        db,
        "run-1",
        outcome=RUN_COMPLETED,
        completed_at="2026-10-04T09:05:00+00:00",
        listings_seen=10,
        new_count=4,
        stored_count=9,
        repeat_count=5,
        skipped_count=1,
        error_count=1,
    )
    assert list_incomplete_runs(db) == []
    row = db.execute("SELECT * FROM runs WHERE run_id='run-1'").fetchone()
    assert row["outcome"] == RUN_COMPLETED
    assert row["started_date"] == "2026-10-04"
    assert row["listings_seen"] == 10
    assert row["stored_count"] == 9
    assert row["error_count"] == 1


def test_start_run_is_idempotent_on_duplicate_id(db):
    start_run(db, run_id="run-1", started_at="2026-10-04T09:00:00+00:00")
    start_run(db, run_id="run-1", started_at="2026-10-04T09:00:00+00:00")
    count = db.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    assert count == 1


# ---------------------------------------------------------------------------
# Cumulative counters and restart durability
# ---------------------------------------------------------------------------


def test_counters_are_cumulative(db):
    assert get_counter(db, "http.attempts") == 0.0
    increment_counter(db, "http.attempts", 3)
    increment_counter(db, "http.attempts")
    assert get_counter(db, "http.attempts") == 4.0
    assert get_counters(db)["http.attempts"] == 4.0


def test_state_survives_reconnect(tmp_path):
    path = str(tmp_path / "monitoring.db")
    conn = connect(path)
    record_discovery(conn, "A1", "2026-10-04T10:00:00+00:00")
    start_run(conn, run_id="run-1", started_at="2026-10-04T09:00:00+00:00")
    increment_counter(conn, "runs.started", 1)
    conn.close()

    reopened = connect(path)
    assert count_unique_listings(reopened) == 1
    assert get_counter(reopened, "runs.started") == 1.0
    # The unfinished run is still visible after a restart.
    assert [r["run_id"] for r in list_incomplete_runs(reopened)] == ["run-1"]
    reopened.close()


# ---------------------------------------------------------------------------
# Archive import
# ---------------------------------------------------------------------------


def test_import_archive_json_is_idempotent(db, tmp_path):
    rows = [
        {"item_id": "111", "scraped_at": "2026-08-30T10:00:00+00:00"},
        {"item_id": "222", "scraped_at": "2026-08-30T11:00:00+00:00"},
    ]
    path = _write_json(tmp_path / "listings-2026-08-30.json", rows)

    first = import_archive(db, path)
    assert first["duplicate"] is False
    assert first["discoveries_changed"] == 2
    assert first["observations_added"] == 2
    assert count_unique_listings(db) == 2
    assert count_observations(db, source=SOURCE_ARCHIVE) == 2

    # Re-importing identical content is a no-op.
    second = import_archive(db, path)
    assert second["duplicate"] is True
    assert second["observations_added"] == 0
    assert count_observations(db) == 2


def test_import_archive_csv(db, tmp_path):
    path = tmp_path / "listings-2026-08-30.csv"
    path.write_text(
        "item_id,title,scraped_at\n"
        "111,Laptop A,2026-08-30T10:00:00+00:00\n",
        encoding="utf-8",
    )
    result = import_archive(db, str(path))
    assert result["rows_seen"] == 1
    assert result["discoveries_changed"] == 1
    assert result["observations_added"] == 1
    assert count_unique_listings(db) == 1


def test_duplicate_snapshot_pairs_do_not_inflate(db, tmp_path):
    """A later cumulative snapshot that repeats an (item_id, timestamp) pair
    seen in an earlier file must not create a second observation."""
    pair = {"item_id": "111", "scraped_at": "2026-08-30T10:00:00+00:00"}
    a = _write_json(tmp_path / "a.json", [pair])
    b = _write_json(
        tmp_path / "b.json",
        [
            pair,
            {"item_id": "333", "scraped_at": "2026-08-31T10:00:00+00:00"},
        ],
    )

    import_archive(db, a)
    import_archive(db, b)

    assert count_unique_listings(db) == 2
    # 111 observed once (deduplicated across files), 333 once.
    assert count_observations(db, source=SOURCE_ARCHIVE) == 2


def test_import_archive_row_without_timestamp(db, tmp_path):
    """A baseline listing with no recoverable date counts all-time but produces
    no observation."""
    path = _write_json(tmp_path / "x.json", [{"item_id": "999"}])
    result = import_archive(db, path)
    assert result["discoveries_changed"] == 1
    assert result["observations_added"] == 0
    assert result["missing_scrape_times"] == 1
    assert count_unique_listings(db) == 1
    assert count_observations(db) == 0


def test_import_archive_does_not_substitute_posted_at_for_scrape_time(db, tmp_path):
    """Posting time must never become discovery or archive observation time."""
    rows = [
        {"item_id": "post-only", "posted_at": "2026-08-20T08:00:00+00:00"},
        {
            "item_id": "invalid-scrape",
            "scraped_at": "not-a-timestamp",
            "posted_at": "2026-08-21T08:00:00+00:00",
        },
    ]
    path = _write_json(tmp_path / "listings-2026-08-30.json", rows)

    result = import_archive(db, path)
    assert result["rows_seen"] == 2
    assert result["discoveries_changed"] == 2
    assert result["observations_added"] == 0
    assert result["missing_scrape_times"] == 2

    # All-time unique IDs count them, bounded discovery counts exclude them,
    # and no archive observations were invented.
    assert count_unique_listings(db) == 2
    assert count_discoveries(db, start_date="2020-01-01") == 0
    assert count_observations(db) == 0

    for item_id in ("post-only", "invalid-scrape"):
        row = db.execute(
            "SELECT discovered_at, discovered_date, discovery_source "
            "FROM discoveries WHERE item_id=?",
            (item_id,),
        ).fetchone()
        assert row["discovered_at"] is None
        assert row["discovered_date"] is None
        assert row["discovery_source"] == SOURCE_UNKNOWN

    # Repeat import stays idempotent.
    second = import_archive(db, path)
    assert second["duplicate"] is True
    assert second["discoveries_changed"] == 0
    assert second["observations_added"] == 0
    assert second["missing_scrape_times"] == 0
    assert count_unique_listings(db) == 2
    assert count_observations(db) == 0


def test_import_archive_preserves_live_discovery_and_reconciles_unknown_baseline(
    db, tmp_path
):
    record_discovery(db, "live-1", "2026-10-04T10:00:00+00:00", source=SOURCE_LIVE)
    record_discovery(db, "base-1", None, source=SOURCE_LIVE)

    rows = [
        {"item_id": "live-1", "scraped_at": "2026-08-30T10:00:00+00:00"},
        {"item_id": "base-1", "scraped_at": "2026-08-31T10:00:00+00:00"},
    ]
    path = _write_json(tmp_path / "listings-2026-08-31.json", rows)

    result = import_archive(db, path)
    assert result["discoveries_changed"] == 1
    assert result["observations_added"] == 2
    assert result["missing_scrape_times"] == 0

    live_row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='live-1'"
    ).fetchone()
    assert live_row["discovered_at"] == "2026-10-04T10:00:00+00:00"
    assert live_row["discovery_source"] == SOURCE_LIVE

    base_row = db.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id='base-1'"
    ).fetchone()
    assert base_row["discovered_at"] == "2026-08-31T10:00:00+00:00"
    assert base_row["discovery_source"] == SOURCE_ARCHIVE


def test_import_archive_unsupported_extension_raises(db, tmp_path):
    path = tmp_path / "listings.txt"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        import_archive(db, str(path))


# ---------------------------------------------------------------------------
# Operator CLI
# ---------------------------------------------------------------------------


def test_cli_stats_returns_zero(tmp_path):
    assert main(["--db", str(tmp_path / "m.db"), "stats"]) == 0


def test_cli_import_returns_zero(db, tmp_path):
    path = _write_json(
        tmp_path / "listings-2026-08-30.json",
        [{"item_id": "111", "scraped_at": "2026-08-30T10:00:00+00:00"}],
    )
    assert main(["--db", str(tmp_path / "m.db"), "import", path]) == 0
