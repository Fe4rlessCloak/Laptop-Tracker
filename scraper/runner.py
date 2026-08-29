"""Orchestration for a single scrape run.

The runner ties together the fetcher, parsers, and storage:

1. For each configured city, fetch the laptops search page.
2. Parse the listing cards and keep only those within the time window.
3. For each kept listing, fetch its item page and enrich it with the
   description and image URLs (text only).
4. Upsert every listing into SQLite.
5. Optionally export to CSV and/or JSON.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Dict, List, Optional

from scraper import config
from scraper.fetcher import Fetcher, FetchError
from scraper.parsers import is_within_hours, parse_item_detail, parse_search_results
from scraper.storage import (
    connect,
    export_csv,
    export_json,
    fetch_all,
    upsert_listing,
)


def build_search_url(
    city_slug: str,
    page: int = 1,
    category: str = "laptops",
) -> str:
    """Build the OLX search URL for a city in the given category.

    ``page`` selects the pagination page (1-based); OLX exposes more results
    via a ``?page=N`` query parameter. ``category`` is a key into
    ``config.CATEGORIES``; unknown values raise ``KeyError`` immediately.
    The URL also requests newest-first ordering (``sorting=desc-creation``)
    so fresh listings appear first.
    """
    path = config.CATEGORIES[category]
    base = (
        f"{config.BASE_URL}/{city_slug}/"
        f"{path}/{config.SEARCH_QUERY}"
    )
    return f"{base}?page={page}&{config.SORT_PARAM}"


class RunSummary:
    """Result counters for a scrape run."""

    def __init__(self) -> None:
        self.fetched = 0
        self.new = 0
        self.updated = 0
        self.skipped = 0
        self.errors = 0

    def __repr__(self) -> str:
        return (
            f"Fetched {self.fetched} listings, "
            f"{self.new} new, {self.updated} updated, "
            f"{self.skipped} skipped, {self.errors} errors"
        )


def run(
    cities: Optional[Dict[str, str]] = None,
    hours: int = config.DEFAULT_HOURS,
    db_path: str = config.DEFAULT_DB_PATH,
    export: Optional[List[str]] = None,
    export_dir: str = config.DEFAULT_EXPORT_DIR,
    delay: float = config.DEFAULT_DELAY,
    category: str = "laptops",
    fetcher: Optional[Fetcher] = None,
) -> RunSummary:
    """Execute a full scrape run and return a summary."""
    cities = cities or config.DEFAULT_CITIES
    export = export or []
    fetcher = fetcher or Fetcher(delay=delay)
    summary = RunSummary()

    conn = connect(db_path)

    try:
        for city, city_slug in cities.items():
            # Page through search results until the time window is exhausted
            # (a page with no fresh listings) or the MAX_PAGES cap is reached.
            # NOTE: we deliberately do NOT early-stop on a duplicate listing.
            # OLX pushes featured ads to the top out of chronological order,
            # so a duplicate on an early page does not guarantee that newer
            # ads are absent from later pages — stopping early would miss them.
            for page in range(1, config.MAX_PAGES + 1):
                url = build_search_url(city_slug, page, category=category)
                try:
                    html = fetcher.get(url)
                except FetchError as exc:
                    print(f"[{city}] search fetch failed: {exc}")
                    summary.errors += 1
                    break

                listings = parse_search_results(html, city)
                kept = [
                    l for l in listings
                    if is_within_hours(l["relative_time"], hours)
                ]
                summary.fetched += len(kept)
                summary.skipped += len(listings) - len(kept)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] PAGE {page}  {len(kept)} HIT  {len(listings) - len(kept)} MISS  ({city})")

                if not kept:
                    # Time-window exhausted: no fresh listings on this page.
                    break

                for listing in kept:
                    try:
                        detail_html = fetcher.get(listing["item_url"])
                        listing = parse_item_detail(detail_html, listing)
                    except FetchError as exc:
                        print(
                            f"[{city}] item {listing['item_id']} fetch failed: {exc}"
                        )
                        summary.errors += 1
                        # Still store the partial listing (title/price/location).
                    finally:
                        fetcher.sleep_between()

                    is_new = upsert_listing(conn, listing)
                    ts = datetime.now().strftime("%H:%M:%S")
                    if is_new:
                        summary.new += 1
                        print(f"[{ts}] HIT   {listing['price']}  {listing['title'][:60]}")
                    else:
                        summary.updated += 1

        today = date.today().isoformat()
        if "csv" in export:
            path = f"{export_dir}/listings-{today}.csv"
            export_csv(fetch_all(conn), path)
            print(f"Exported CSV -> {path}")
        if "json" in export:
            path = f"{export_dir}/listings-{today}.json"
            export_json(fetch_all(conn), path)
            print(f"Exported JSON -> {path}")
    finally:
        conn.close()

    return summary
