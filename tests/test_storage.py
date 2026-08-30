"""Unit tests for the SQLite storage layer."""

import json
import os
import tempfile

import pytest

from scraper.storage import (
    connect,
    count_listings,
    export_csv,
    export_json,
    fetch_all,
    listing_exists,
    upsert_listing,
)

SAMPLE = {
    "item_id": "1077082458",
    "title": "Laptop Core i5 i7 Dell Hp Lenovo",
    "price": "Rs 39,000",
    "price_numeric": 39000.0,
    "currency": "PKR",
    "location": "Allama Iqbal Town - Huma Block, Lahore",
    "city": "islamabad",
    "relative_time": "1 day ago",
    "posted_at": "2026-08-03T20:00:00+00:00",
    "description": "A used laptop in good condition.",
    "image_urls": ["https://images.olx.com.pk/thumbnails/1-400x300.jpeg"],
    "item_url": "https://www.olx.com.pk/item/laptop-iid-1077082458",
    "is_featured": True,
}


@pytest.fixture()
def db(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    yield conn
    conn.close()


def test_connect_creates_schema(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {t["name"] for t in tables}
    assert "listings" in names


def test_upsert_inserts_new(db):
    is_new = upsert_listing(db, SAMPLE)
    assert is_new is True
    assert count_listings(db) == 1


def test_upsert_updates_existing(db):
    upsert_listing(db, SAMPLE)
    updated = dict(SAMPLE)
    updated["title"] = "Updated title"
    is_new = upsert_listing(db, updated)
    assert is_new is False
    assert count_listings(db) == 1

    rows = fetch_all(db)
    assert rows[0]["title"] == "Updated title"


def test_listing_exists(db):
    assert listing_exists(db, SAMPLE["item_id"]) is False
    upsert_listing(db, SAMPLE)
    assert listing_exists(db, SAMPLE["item_id"]) is True
    assert listing_exists(db, "999999999") is False


def test_fetch_all_parses_image_urls(db):
    upsert_listing(db, SAMPLE)
    rows = fetch_all(db)
    assert rows[0]["image_urls"] == SAMPLE["image_urls"]
    assert rows[0]["is_featured"] is True


def test_export_csv(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    upsert_listing(conn, SAMPLE)
    path = str(tmp_path / "out.csv")
    export_csv(fetch_all(conn), path)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "item_id" in content
    assert SAMPLE["item_id"] in content
    conn.close()


def test_export_json(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    upsert_listing(conn, SAMPLE)
    path = str(tmp_path / "out.json")
    export_json(fetch_all(conn), path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data[0]["item_id"] == SAMPLE["item_id"]
    assert data[0]["image_urls"] == SAMPLE["image_urls"]
    conn.close()


# ---------------------------------------------------------------------------
# seller_name column (Release 1.0.0)
# ---------------------------------------------------------------------------


def test_seller_name_round_trips(db):
    """A listing with seller_name stored, then read back, must equal the input."""
    listing = dict(SAMPLE, seller_name="Ayesha Khan")
    upsert_listing(db, listing)
    rows = fetch_all(db)
    assert rows[0]["seller_name"] == "Ayesha Khan"


def test_seller_name_absent_stores_as_none(db):
    """A listing without seller_name must read back as None (not raise)."""
    listing = dict(SAMPLE)
    listing.pop("seller_name", None)
    upsert_listing(db, listing)
    rows = fetch_all(db)
    assert rows[0]["seller_name"] is None


def test_seller_name_appears_in_csv_export(tmp_path):
    """The CSV export must include the seller_name column."""
    conn = connect(str(tmp_path / "test.db"))
    upsert_listing(conn, dict(SAMPLE, seller_name="Bilal Ahmed"))
    path = str(tmp_path / "out.csv")
    export_csv(fetch_all(conn), path)
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "seller_name" in content
    assert "Bilal Ahmed" in content
    conn.close()


def test_schema_migrates_legacy_db_without_seller_name(tmp_path):
    """A DB created by an older release (no seller_name column) must be
    upgraded in place so the new column appears without manual migration."""
    import sqlite3

    legacy_path = str(tmp_path / "legacy.db")
    # Build a "legacy" schema without seller_name, exactly as the prior
    # release would have created it.
    legacy = sqlite3.connect(legacy_path)
    legacy.execute(
        """
        CREATE TABLE listings (
            item_id       TEXT PRIMARY KEY,
            title         TEXT,
            price         TEXT,
            price_numeric REAL,
            currency      TEXT,
            location      TEXT,
            city          TEXT,
            relative_time TEXT,
            posted_at     TEXT,
            description   TEXT,
            image_urls    TEXT,
            item_url      TEXT,
            is_featured   INTEGER,
            scraped_at    TEXT
        )
        """
    )
    legacy.execute(
        """
        INSERT INTO listings (item_id, title) VALUES (?, ?)
        """,
        ("legacy-id-1", "Old Laptop"),
    )
    legacy.commit()
    legacy.close()

    # Re-open via the production connect(); the migration should add
    # the seller_name column without raising.
    conn = connect(legacy_path)
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(listings)").fetchall()
    }
    assert "seller_name" in cols
    # The pre-existing row must still be present, with seller_name NULL.
    rows = fetch_all(conn)
    assert any(r["item_id"] == "legacy-id-1" and r["seller_name"] is None for r in rows)
    conn.close()
