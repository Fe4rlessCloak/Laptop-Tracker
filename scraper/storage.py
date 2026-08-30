"""SQLite storage layer with upsert semantics and CSV/JSON export.

The scraper stores listings in a local SQLite database. Each listing is keyed
by its unique OLX item ID so that repeated runs *upsert* (insert new rows,
update existing ones) rather than creating duplicates. This lets the user build
a clean history of listings over time.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Columns stored for each listing, in a stable order used by both the schema
# and the CSV export.
LISTING_COLUMNS = [
    "item_id",
    "title",
    "price",
    "price_numeric",
    "currency",
    "location",
    "city",
    "relative_time",
    "posted_at",
    "description",
    "image_urls",
    "item_url",
    "is_featured",
    "scraped_at",
    "seller_name",
]


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite database and ensure the schema."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the listings table if it does not already exist.

    For databases created by an older version of the scraper (before
    ``seller_name`` was added in Release 1.0.0), perform an idempotent
    ``ALTER TABLE ... ADD COLUMN`` so the new column is present without
    requiring a manual migration. ``PRAGMA table_info`` reports the existing
    columns; we add ``seller_name`` only if it is absent.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
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
            scraped_at    TEXT,
            seller_name   TEXT
        )
        """
    )
    _ensure_column(conn, "listings", "seller_name", "TEXT")
    conn.commit()


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """Add ``column`` to ``table`` if it does not already exist.

    This is the migration pattern used to bring older databases created by
    earlier releases up to the current schema. It is intentionally
    conservative: it inspects ``PRAGMA table_info`` and only runs
    ``ALTER TABLE ... ADD COLUMN`` when the column is missing. The operation
    is a no-op for databases already at the current schema.
    """
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upsert_listing(conn: sqlite3.Connection, listing: Dict[str, Any]) -> bool:
    """Insert a new listing or update an existing one by item_id.

    Returns True if the row was newly inserted, False if it was an update.
    """
    row = _listing_to_row(listing)
    placeholders = ", ".join("?" for _ in LISTING_COLUMNS)
    columns = ", ".join(LISTING_COLUMNS)
    updates = ", ".join(f"{col}=excluded.{col}" for col in LISTING_COLUMNS)

    before = conn.execute(
        "SELECT 1 FROM listings WHERE item_id = ?", (row["item_id"],)
    ).fetchone()
    is_new = before is None

    conn.execute(
        f"""
        INSERT INTO listings ({columns})
        VALUES ({placeholders})
        ON CONFLICT(item_id) DO UPDATE SET {updates}
        """,
        [row[col] for col in LISTING_COLUMNS],
    )
    conn.commit()
    return is_new


def _listing_to_row(listing: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a listing dict into the storage row shape."""
    image_urls = listing.get("image_urls") or []
    if isinstance(image_urls, list):
        image_urls = json.dumps(image_urls)

    return {
        "item_id": listing.get("item_id"),
        "title": listing.get("title"),
        "price": listing.get("price"),
        "price_numeric": listing.get("price_numeric"),
        "currency": listing.get("currency", "PKR"),
        "location": listing.get("location"),
        "city": listing.get("city"),
        "relative_time": listing.get("relative_time"),
        "posted_at": listing.get("posted_at"),
        "description": listing.get("description"),
        "image_urls": image_urls,
        "item_url": listing.get("item_url"),
        "is_featured": 1 if listing.get("is_featured") else 0,
        "scraped_at": listing.get("scraped_at") or _now_iso(),
        "seller_name": listing.get("seller_name"),
    }


def _row_to_listing(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a DB row back into a plain dict (image_urls parsed to a list)."""
    listing = dict(row)
    try:
        listing["image_urls"] = json.loads(listing["image_urls"] or "[]")
    except (json.JSONDecodeError, TypeError):
        listing["image_urls"] = []
    listing["is_featured"] = bool(listing["is_featured"])
    return listing


def listing_exists(conn: sqlite3.Connection, item_id: str) -> bool:
    """Return True if a listing with the given item_id is already stored.

    Available for callers that need a cheap presence check. The runner
    deliberately does NOT use this for a duplicate early-stop: featured ads
    break OLX's newest-first ordering, so a duplicate on an early page does
    not guarantee newer ads are absent from later pages. The runner stops on
    time-window exhaustion or the MAX_PAGES cap instead.
    """
    row = conn.execute(
        "SELECT 1 FROM listings WHERE item_id = ?", (item_id,)
    ).fetchone()
    return row is not None


def fetch_all(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Return all stored listings as dicts."""
    rows = conn.execute(f"SELECT {', '.join(LISTING_COLUMNS)} FROM listings").fetchall()
    return [_row_to_listing(r) for r in rows]


def export_csv(listings: List[Dict[str, Any]], path: str) -> None:
    """Write listings to a CSV file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LISTING_COLUMNS)
        writer.writeheader()
        for listing in listings:
            row = _listing_to_row(listing)
            writer.writerow({col: row.get(col, "") for col in LISTING_COLUMNS})


def export_json(listings: List[Dict[str, Any]], path: str) -> None:
    """Write listings to a JSON file (image_urls as a list)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(listings, fh, ensure_ascii=False, indent=2)


def count_listings(conn: sqlite3.Connection) -> int:
    """Return the total number of stored listings."""
    row = conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()
    return int(row["n"]) if row else 0
