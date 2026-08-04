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
