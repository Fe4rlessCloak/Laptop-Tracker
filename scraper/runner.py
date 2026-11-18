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

import os
import sys
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from scraper import config
from scraper.fetcher import FetchBlocked, Fetcher, FetchError
from scraper.monitoring import (
    OUTCOME_FAILED,
    OUTCOME_STORED,
    PAGE_TYPE_DETAIL,
    PAGE_TYPE_SEARCH,
    RUN_COMPLETED,
    RUN_COMPLETED_WITH_FETCH_ERRORS,
    RUN_FAILED,
    SOURCE_LIVE,
    connect as mon_connect,
    finish_run,
    record_discovery,
    record_observation,
    record_request_event,
    start_run,
)
from scraper.parsers import is_within_hours, parse_item_detail, parse_search_results
from scraper.storage import (
    connect,
    export_csv,
    export_json,
    fetch_all,
    get_listing,
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


def _resolve_monitoring_db_path(
    db_path: str, monitoring_db_path: Optional[str]
) -> Optional[str]:
    """Resolve the monitoring DB path without touching production data in tests."""
    if monitoring_db_path == "":
        return None
    if monitoring_db_path is not None:
        return monitoring_db_path
    if db_path == config.DEFAULT_DB_PATH:
        return config.DEFAULT_MONITORING_DB_PATH
    return os.path.join(
        os.path.dirname(os.path.abspath(db_path)), "monitoring.db"
    )


def _safe_mon_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke a monitoring write safely; log warnings without breaking scrapes."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        print(f"[monitoring] warning: {exc}", file=sys.stderr)
        return None


def run(
    cities: Optional[Dict[str, str]] = None,
    hours: int = config.DEFAULT_HOURS,
    db_path: str = config.DEFAULT_DB_PATH,
    export: Optional[List[str]] = None,
    export_dir: str = config.DEFAULT_EXPORT_DIR,
    delay: float = config.DEFAULT_DELAY,
    category: str = "laptops",
    fetcher: Optional[Fetcher] = None,
    monitoring_db_path: Optional[str] = None,
) -> RunSummary:
    """Execute a full scrape run and return a summary."""
    cities = cities or config.DEFAULT_CITIES
    export = export or []
    fetcher = fetcher or Fetcher(delay=delay)
    summary = RunSummary()
    run_t0 = time.monotonic()
    detail_fetches = 0
    cap_logged = False

    conn = connect(db_path)
    resolved_mon_path = _resolve_monitoring_db_path(db_path, monitoring_db_path)
    mon_conn = None
    run_id: Optional[str] = None
    if resolved_mon_path is not None:
        mon_conn = _safe_mon_call(mon_connect, resolved_mon_path)
        if mon_conn is not None:
            run_id = _safe_mon_call(
                start_run,
                mon_conn,
                run_id=f"run-{datetime.now(timezone.utc).isoformat()}-{uuid.uuid4().hex[:8]}",
            )

    has_on_attempt = hasattr(fetcher, "on_attempt")
    has_ctx = hasattr(fetcher, "set_attempt_context")
    previous_on_attempt = getattr(fetcher, "on_attempt", None) if has_on_attempt else None

    def _on_attempt(event: Dict[str, Any]) -> None:
        if mon_conn is None or not event.get("page_type"):
            return
        _safe_mon_call(
            record_request_event,
            mon_conn,
            run_id=run_id,
            page_type=event["page_type"],
            city=event.get("city"),
            attempt_number=event["attempt_number"],
            status_code=event.get("status_code"),
            outcome=event["outcome"],
            is_final=bool(event.get("is_final")),
            duration_ms=event["duration_ms"],
            recorded_at=event.get("recorded_at"),
        )

    if has_on_attempt:
        fetcher.on_attempt = _on_attempt

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
                if has_ctx:
                    fetcher.set_attempt_context(
                        page_type=PAGE_TYPE_SEARCH, city=city
                    )
                try:
                    html = fetcher.get(url)
                except FetchBlocked as exc:
                    print(f"[{city}] blocked, aborting run: {exc}")
                    summary.errors += 1
                    raise
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
                    item_id = listing.get("item_id")
                    existing = (
                        get_listing(conn, str(item_id)) if item_id else None
                    )
                    if existing and existing.get("description"):
                        # An earlier run already enriched this listing. Reuse
                        # its detail fields rather than spending a request, so
                        # a steady-state run only fetches genuinely new items.
                        listing = {
                            **listing,
                            "description": existing.get("description"),
                            "image_urls": existing.get("image_urls") or [],
                            "seller_name": existing.get("seller_name"),
                        }
                    elif detail_fetches < config.MAX_DETAIL_FETCHES_PER_RUN:
                        detail_fetches += 1
                        if has_ctx:
                            fetcher.set_attempt_context(
                                page_type=PAGE_TYPE_DETAIL, city=city
                            )
                        try:
                            detail_html = fetcher.get(listing["item_url"])
                            listing = parse_item_detail(detail_html, listing)
                        except FetchBlocked:
                            summary.errors += 1
                            raise
                        except FetchError as exc:
                            print(
                                f"[{city}] item {listing['item_id']} fetch failed: {exc}"
                            )
                            summary.errors += 1
                            # Still store the partial listing (title/price/location).
                        finally:
                            fetcher.sleep_between()
                    elif not cap_logged:
                        cap_logged = True
                        print(
                            f"[cap] detail fetch limit "
                            f"({config.MAX_DETAIL_FETCHES_PER_RUN}) reached; "
                            "storing remaining listings from card data"
                        )

                    encounter_ts = (
                        listing.get("scraped_at")
                        or datetime.now(timezone.utc).isoformat()
                    )
                    try:
                        is_new = upsert_listing(conn, listing)
                    except Exception:
                        summary.errors += 1
                        if mon_conn is not None and item_id:
                            _safe_mon_call(
                                record_observation,
                                mon_conn,
                                str(item_id),
                                encounter_ts,
                                outcome=OUTCOME_FAILED,
                                source=SOURCE_LIVE,
                                run_id=run_id,
                                city=city,
                            )
                        raise

                    if mon_conn is not None and item_id:
                        _safe_mon_call(
                            record_discovery,
                            mon_conn,
                            str(item_id),
                            encounter_ts,
                            source=SOURCE_LIVE,
                        )
                        _safe_mon_call(
                            record_observation,
                            mon_conn,
                            str(item_id),
                            encounter_ts,
                            outcome=OUTCOME_STORED,
                            source=SOURCE_LIVE,
                            run_id=run_id,
                            city=city,
                        )

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

        if mon_conn is not None and run_id is not None:
            run_outcome = (
                RUN_COMPLETED_WITH_FETCH_ERRORS
                if summary.errors > 0
                else RUN_COMPLETED
            )
            _safe_mon_call(
                finish_run,
                mon_conn,
                run_id,
                outcome=run_outcome,
                duration_ms=(time.monotonic() - run_t0) * 1000.0,
                listings_seen=summary.fetched,
                new_count=summary.new,
                stored_count=summary.new + summary.updated,
                repeat_count=summary.updated,
                skipped_count=summary.skipped,
                error_count=summary.errors,
            )
    except Exception:
        if mon_conn is not None and run_id is not None:
            _safe_mon_call(
                finish_run,
                mon_conn,
                run_id,
                outcome=RUN_FAILED,
                duration_ms=(time.monotonic() - run_t0) * 1000.0,
                listings_seen=summary.fetched,
                new_count=summary.new,
                stored_count=summary.new + summary.updated,
                repeat_count=summary.updated,
                skipped_count=summary.skipped,
                error_count=summary.errors,
            )
        raise
    finally:
        if has_on_attempt:
            fetcher.on_attempt = previous_on_attempt
        if mon_conn is not None:
            try:
                mon_conn.close()
            except Exception:
                pass
        conn.close()

    return summary
