"""Read-only Web UI and JSON API for OLX laptop listings and performance.

Serves two clean, offline-capable HTML views (plus JSON endpoints) backed
directly by ``olx.db`` and ``monitoring.db`` opened strictly read-only:

* ``GET /`` — Searchable, filterable laptop listings (defaults to laptops
  first discovered today in ``Asia/Karachi``).
* ``GET /performance`` — Latency overview (Average, P50, P95, P99 / slowest 1%,
  P99.9 / slowest 0.1%), failure/retry rates, and scraper run history.
* ``GET /api/listings``, ``GET /api/performance``, ``GET /health`` — JSON APIs.
"""

from __future__ import annotations

import argparse
import html
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from scraper import config
from scraper.monitoring import (
    KARACHI_TZ,
    PAGE_TYPE_DETAIL,
    PAGE_TYPE_SEARCH,
    SOURCE_ARCHIVE,
    VALID_PERFORMANCE_WINDOWS,
    count_discoveries,
    count_observations,
    count_unique_listings,
    count_unknown_discoveries,
    get_performance_summary,
    open_readonly_db,
    parse_timestamp,
)

VALID_LISTING_MODES = ("discovered_today", "seen_today", "all")
SORT_CLAUSES = {
    "newest": "COALESCE(d.discovered_at, l.scraped_at) DESC, l.item_id DESC",
    "price_asc": (
        "(l.price_numeric IS NULL) ASC, l.price_numeric ASC, "
        "COALESCE(d.discovered_at, l.scraped_at) DESC"
    ),
    "price_desc": (
        "(l.price_numeric IS NULL) ASC, l.price_numeric DESC, "
        "COALESCE(d.discovered_at, l.scraped_at) DESC"
    ),
}
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _escape_like(value: str) -> str:
    """Escape LIKE wildcard characters so user text matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _safe_http_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    stripped = url.strip()
    if stripped.startswith(("https://", "http://")):
        return stripped
    return None


def _parse_optional_date(raw: Optional[str], label: str) -> Optional[date]:
    if raw is None or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid {label} date {raw!r}; expected YYYY-MM-DD.") from exc


def _parse_optional_price(raw: Optional[str], label: str) -> Optional[float]:
    if raw is None or not raw.strip():
        return None
    try:
        val = float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid {label} price {raw!r}; expected a number.") from exc
    if val < 0:
        raise ValueError(f"{label} price cannot be negative.")
    return val


def _format_karachi_dt(value: Optional[str]) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "Unknown"
    return parsed.astimezone(KARACHI_TZ).strftime("%Y-%m-%d %H:%M PKT")


def _format_karachi_date(value: Optional[str]) -> str:
    if not value:
        return "Unknown"
    return value


def _format_ms(value: Optional[float]) -> str:
    if value is None:
        return "No data"
    if value >= 1000.0:
        return f"{value / 1000.0:.2f} s ({value:.0f} ms)"
    return f"{value:.1f} ms"


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "No data"
    return f"{value * 100.0:.1f}%"


def _open_olx_with_monitoring(
    db_path: str, monitoring_db_path: Optional[str]
) -> Tuple[sqlite3.Connection, bool]:
    """Open ``olx.db`` read-only and optionally attach ``monitoring.db`` read-only."""
    conn = open_readonly_db(db_path)
    has_mon = bool(monitoring_db_path and os.path.exists(monitoring_db_path))
    if has_mon:
        mon_uri = Path(monitoring_db_path).resolve().as_uri() + "?mode=ro"
        conn.execute("ATTACH DATABASE ? AS mon", (mon_uri,))
    return conn, has_mon


def _monitoring_overview(
    mon_path: Optional[str], today_str: str, tomorrow_str: str
) -> Dict[str, Any]:
    if not mon_path or not os.path.exists(mon_path):
        return {
            "monitoring_db_exists": False,
            "all_time_unique": 0,
            "discovered_today": 0,
            "observations_today": 0,
            "unique_seen_today": 0,
            "unknown_discovery_count": 0,
            "has_archive_estimates": False,
        }
    mon = open_readonly_db(mon_path)
    try:
        unique_seen_row = mon.execute(
            "SELECT COUNT(DISTINCT item_id) AS n FROM observations WHERE observed_date = ?",
            (today_str,),
        ).fetchone()
        arch_row = mon.execute(
            "SELECT 1 FROM discoveries WHERE discovery_source = ? LIMIT 1",
            (SOURCE_ARCHIVE,),
        ).fetchone()
        return {
            "monitoring_db_exists": True,
            "all_time_unique": count_unique_listings(mon),
            "discovered_today": count_discoveries(
                mon, start_date=today_str, end_date=tomorrow_str
            ),
            "observations_today": count_observations(
                mon, start_date=today_str, end_date=tomorrow_str
            ),
            "unique_seen_today": int(unique_seen_row["n"]) if unique_seen_row else 0,
            "unknown_discovery_count": count_unknown_discoveries(mon),
            "has_archive_estimates": arch_row is not None,
        }
    finally:
        mon.close()


def query_listings(
    db_path: str,
    monitoring_db_path: Optional[str],
    *,
    mode: str = "discovered_today",
    q: Optional[str] = None,
    city: Optional[str] = None,
    min_price: Optional[str] = None,
    max_price: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Query listings read-only with validation and safe SQL parameterization."""
    now = now_utc.astimezone(timezone.utc) if now_utc else datetime.now(timezone.utc)
    today_date = now.astimezone(KARACHI_TZ).date()
    today_str = today_date.isoformat()
    tomorrow_str = (today_date + timedelta(days=1)).isoformat()

    overview = _monitoring_overview(monitoring_db_path, today_str, tomorrow_str)
    olx_exists = os.path.exists(db_path)

    page = max(1, int(page))
    page_size = max(1, min(MAX_PAGE_SIZE, int(page_size)))

    base_result: Dict[str, Any] = {
        "olx_db_exists": olx_exists,
        **overview,
        "today_karachi": today_str,
        "mode": mode if mode in VALID_LISTING_MODES else "discovered_today",
        "sort": sort if sort in SORT_CLAUSES else "newest",
        "page": page,
        "page_size": page_size,
        "total": 0,
        "total_pages": 0,
        "items": [],
        "available_cities": list(config.DEFAULT_CITIES.keys()),
        "validation_error": None,
        "bootstrap_note": None,
    }

    if mode not in VALID_LISTING_MODES:
        base_result["validation_error"] = (
            f"Invalid mode {mode!r}; expected one of {', '.join(VALID_LISTING_MODES)}."
        )
        return base_result
    if sort not in SORT_CLAUSES:
        base_result["validation_error"] = (
            f"Invalid sort {sort!r}; expected one of {', '.join(SORT_CLAUSES)}."
        )
        return base_result

    try:
        parsed_min = _parse_optional_price(min_price, "minimum")
        parsed_max = _parse_optional_price(max_price, "maximum")
        if parsed_min is not None and parsed_max is not None and parsed_min > parsed_max:
            raise ValueError("Minimum price cannot exceed maximum price.")
        parsed_start = _parse_optional_date(start_date, "start")
        parsed_end = _parse_optional_date(end_date, "end")
        if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
            raise ValueError("Start date cannot be after end date.")
    except ValueError as exc:
        base_result["validation_error"] = str(exc)
        return base_result

    if not olx_exists:
        base_result["bootstrap_note"] = (
            "Listing database has not been created yet. Run the scraper once to populate listings."
        )
        return base_result

    conn, has_mon = _open_olx_with_monitoring(db_path, monitoring_db_path)
    try:
        city_rows = conn.execute(
            "SELECT DISTINCT city FROM listings WHERE city IS NOT NULL AND city != '' ORDER BY city"
        ).fetchall()
        cities_set = list(config.DEFAULT_CITIES.keys())
        for r in city_rows:
            if r["city"] not in cities_set:
                cities_set.append(r["city"])
        base_result["available_cities"] = cities_set

        if mode in ("discovered_today", "seen_today") and not has_mon:
            base_result["bootstrap_note"] = (
                "Monitoring database is not initialized yet, so today's discovery/observation "
                "filters have no records yet. Switch to 'All listings' or run the scraper once."
            )
            return base_result

        if (parsed_start or parsed_end) and not has_mon:
            base_result["bootstrap_note"] = (
                "Monitoring database is not initialized yet; discovery date-range filters "
                "require monitoring.db."
            )
            return base_result

        if has_mon:
            from_sql = (
                "FROM listings l LEFT JOIN mon.discoveries d ON d.item_id = l.item_id"
            )
            disc_cols = "d.discovered_at, d.discovered_date, d.discovery_source"
        else:
            from_sql = "FROM listings l"
            disc_cols = (
                "NULL AS discovered_at, NULL AS discovered_date, NULL AS discovery_source"
            )

        clauses: List[str] = []
        params: List[Any] = []

        if mode == "discovered_today":
            clauses.append("d.discovered_date = ?")
            params.append(today_str)
        elif mode == "seen_today":
            clauses.append(
                "EXISTS (SELECT 1 FROM mon.observations o "
                "WHERE o.item_id = l.item_id AND o.observed_date = ?)"
            )
            params.append(today_str)
        elif has_mon:
            if parsed_start is not None:
                clauses.append("d.discovered_date >= ?")
                params.append(parsed_start.isoformat())
            if parsed_end is not None:
                end_excl = (parsed_end + timedelta(days=1)).isoformat()
                clauses.append("d.discovered_date < ?")
                params.append(end_excl)

        if city and city.lower() != "all":
            clauses.append("LOWER(l.city) = LOWER(?)")
            params.append(city.strip())

        if q and q.strip():
            like_pattern = f"%{_escape_like(q.strip())}%"
            clauses.append(
                "(LOWER(COALESCE(l.title, '')) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(COALESCE(l.description, '')) LIKE LOWER(?) ESCAPE '\\')"
            )
            params.extend([like_pattern, like_pattern])

        if parsed_min is not None:
            clauses.append("l.price_numeric IS NOT NULL AND l.price_numeric >= ?")
            params.append(parsed_min)
        if parsed_max is not None:
            clauses.append("l.price_numeric IS NOT NULL AND l.price_numeric <= ?")
            params.append(parsed_max)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n {from_sql}{where_sql}", params
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        total_pages = (total + page_size - 1) // page_size if total else 0
        if total_pages and page > total_pages:
            page = total_pages
        offset = (page - 1) * page_size

        order_sql = SORT_CLAUSES[sort] if has_mon else SORT_CLAUSES[sort].replace(
            "COALESCE(d.discovered_at, l.scraped_at)", "l.scraped_at"
        )
        rows = conn.execute(
            f"""
            SELECT l.item_id, l.title, l.price, l.price_numeric, l.currency,
                   l.location, l.city, l.relative_time, l.description,
                   l.item_url, l.is_featured, l.scraped_at, l.seller_name,
                   {disc_cols}
              {from_sql}{where_sql}
          ORDER BY {order_sql}
             LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        items = []
        for r in rows:
            item = dict(r)
            item["is_featured"] = bool(item["is_featured"])
            item["safe_url"] = _safe_http_url(item.get("item_url"))
            items.append(item)

        base_result["page"] = page
        base_result["total"] = total
        base_result["total_pages"] = total_pages
        base_result["items"] = items
        return base_result
    finally:
        conn.close()


def query_performance(
    monitoring_db_path: Optional[str],
    *,
    window: str = "all",
    stale_hours: float = 26.0,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Query performance metrics and run history read-only."""
    if window not in VALID_PERFORMANCE_WINDOWS:
        return {
            "monitoring_db_exists": bool(
                monitoring_db_path and os.path.exists(monitoring_db_path)
            ),
            "window": "all",
            "validation_error": (
                f"Invalid window {window!r}; expected one of "
                f"{', '.join(VALID_PERFORMANCE_WINDOWS)}."
            ),
            "overall": None,
            "by_page_type": {},
            "recent_runs": [],
            "latest_run": None,
            "latest_completed_run": None,
            "latest_successful_run": None,
            "hours_since_completed": None,
            "stale_hours_threshold": stale_hours,
            "is_stale": False,
        }

    if not monitoring_db_path or not os.path.exists(monitoring_db_path):
        empty_stats = {
            "count": 0,
            "avg_ms": None,
            "min_ms": None,
            "max_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "p999_ms": None,
            "total_attempts": 0,
            "failed_attempts": 0,
            "attempt_failure_rate": None,
            "logical_fetches": 0,
            "final_failures": 0,
            "final_fetch_failure_rate": None,
            "retries": 0,
        }
        return {
            "monitoring_db_exists": False,
            "window": window,
            "selected_run_id": None,
            "validation_error": None,
            "overall": empty_stats,
            "by_page_type": {
                PAGE_TYPE_SEARCH: dict(empty_stats),
                PAGE_TYPE_DETAIL: dict(empty_stats),
            },
            "recent_runs": [],
            "latest_run": None,
            "latest_completed_run": None,
            "latest_successful_run": None,
            "hours_since_completed": None,
            "stale_hours_threshold": stale_hours,
            "is_stale": False,
        }

    mon = open_readonly_db(monitoring_db_path)
    try:
        summary = get_performance_summary(
            mon, window=window, now_utc=now_utc, stale_hours=stale_hours
        )
        summary["monitoring_db_exists"] = True
        summary["validation_error"] = None
        return summary
    finally:
        mon.close()


# ---------------------------------------------------------------------------
# HTML Rendering (offline-safe, escaped, zero external CDN assets)
# ---------------------------------------------------------------------------

_BASE_CSS = """
:root {
  --bg: #0f172a; --surface: #1e293b; --surface-2: #0b1220;
  --border: #334155; --text: #f1f5f9; --muted: #94a3b8;
  --accent: #38bdf8; --ok: #22c55e; --warn: #f59e0b; --err: #ef4444;
}
* { box-sizing: border-box; }
body {
  margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.45;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 20px; }
header {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--border); margin-bottom: 20px;
}
header h1 { margin: 0; font-size: 1.35rem; }
nav { display: flex; gap: 10px; }
nav a {
  padding: 7px 14px; border-radius: 6px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font-weight: 500;
}
nav a.active { background: var(--accent); color: #0f172a; border-color: var(--accent); }
.cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px; margin-bottom: 18px;
}
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 14px;
}
.card .label { font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.card .val { font-size: 1.35rem; font-weight: 700; margin-top: 4px; }
.card .sub { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }
.banner {
  padding: 10px 14px; border-radius: 6px; margin-bottom: 16px;
  border: 1px solid var(--border); background: var(--surface);
}
.banner.warn { border-color: var(--warn); color: #fde68a; background: rgba(245,158,11,0.12); }
.banner.err { border-color: var(--err); color: #fecaca; background: rgba(239,68,68,0.14); }
.banner.info { border-color: var(--accent); color: #bae6fd; background: rgba(56,189,248,0.10); }
form.filters {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px; margin-bottom: 18px;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px;
  align-items: end;
}
label.field { display: flex; flex-direction: column; gap: 4px; font-size: 0.82rem; color: var(--muted); }
input, select {
  padding: 7px 9px; border-radius: 6px; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--text); font-size: 0.92rem;
}
.btn-row { display: flex; gap: 8px; align-items: center; }
button, .btn {
  padding: 8px 14px; border-radius: 6px; border: 1px solid var(--accent);
  background: var(--accent); color: #0f172a; font-weight: 600; cursor: pointer;
  font-size: 0.9rem; display: inline-block;
}
.btn.secondary { background: transparent; color: var(--text); border-color: var(--border); }
table {
  width: 100%; border-collapse: collapse; background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
}
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-size: 0.78rem; text-transform: uppercase; color: var(--muted); background: var(--surface-2); }
tr:last-child td { border-bottom: none; }
.badge {
  display: inline-block; padding: 2px 7px; border-radius: 4px;
  font-size: 0.75rem; font-weight: 600; background: var(--surface-2); border: 1px solid var(--border);
}
.badge.ok { border-color: var(--ok); color: #86efac; }
.badge.warn { border-color: var(--warn); color: #fde68a; }
.badge.err { border-color: var(--err); color: #fecaca; }
.desc { color: var(--muted); font-size: 0.84rem; margin-top: 4px; }
.pager { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; }
.mono { font-variant-numeric: tabular-nums; }
"""


def _page_shell(title: str, active_tab: str, body: str) -> str:
    listings_cls = "active" if active_tab == "listings" else ""
    perf_cls = "active" if active_tab == "performance" else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} — OLX Laptop Tracker</title>
  <style>{_BASE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>OLX Laptop Tracker</h1>
      <nav>
        <a href="/" class="{listings_cls}">Listings</a>
        <a href="/performance" class="{perf_cls}">Performance</a>
      </nav>
    </header>
    {body}
  </div>
</body>
</html>"""


def _render_listings_html(
    result: Dict[str, Any],
    *,
    q: str = "",
    city: str = "all",
    min_price: str = "",
    max_price: str = "",
    start_date: str = "",
    end_date: str = "",
) -> str:
    mode = result["mode"]
    sort = result["sort"]
    parts: List[str] = []

    parts.append(
        f"""
        <div class="cards">
          <div class="card">
            <div class="label">Discovered Today ({html.escape(result['today_karachi'])})</div>
            <div class="val mono">{result['discovered_today']}</div>
            <div class="sub">Unique new listing IDs</div>
          </div>
          <div class="card">
            <div class="label">Seen Today</div>
            <div class="val mono">{result['unique_seen_today']}</div>
            <div class="sub">{result['observations_today']} total observations</div>
          </div>
          <div class="card">
            <div class="label">All-Time Unique IDs</div>
            <div class="val mono">{result['all_time_unique']}</div>
            <div class="sub">{result['unknown_discovery_count']} unknown discovery date</div>
          </div>
          <div class="card">
            <div class="label">Matching Results</div>
            <div class="val mono">{result['total']}</div>
            <div class="sub">Page {result['page']} of {max(1, result['total_pages'])}</div>
          </div>
        </div>
        """
    )

    if result["has_archive_estimates"]:
        parts.append(
            '<div class="banner info">Historical discovery dates include estimates reconstructed from daily exports.</div>'
        )
    if result["bootstrap_note"]:
        parts.append(
            f'<div class="banner warn">{html.escape(result["bootstrap_note"])}</div>'
        )
    if result["validation_error"]:
        parts.append(
            f'<div class="banner err">{html.escape(result["validation_error"])}</div>'
        )

    mode_options = "".join(
        f'<option value="{val}"{" selected" if mode == val else ""}>{html.escape(label)}</option>'
        for val, label in (
            ("discovered_today", "Discovered today"),
            ("seen_today", "Seen today"),
            ("all", "All listings"),
        )
    )
    city_options = '<option value="all">All cities</option>' + "".join(
        f'<option value="{html.escape(c)}"{" selected" if city.lower() == c.lower() else ""}>{html.escape(c.title())}</option>'
        for c in result["available_cities"]
    )
    sort_options = "".join(
        f'<option value="{val}"{" selected" if sort == val else ""}>{html.escape(label)}</option>'
        for val, label in (
            ("newest", "Newest discovered"),
            ("price_asc", "Price: low to high"),
            ("price_desc", "Price: high to low"),
        )
    )

    parts.append(
        f"""
        <form class="filters" method="get" action="/">
          <label class="field">View
            <select name="mode">{mode_options}</select>
          </label>
          <label class="field">Search title / description
            <input type="text" name="q" value="{html.escape(q)}" placeholder="e.g. ThinkPad, i7, 16GB" />
          </label>
          <label class="field">City
            <select name="city">{city_options}</select>
          </label>
          <label class="field">Min price (PKR)
            <input type="number" name="min_price" min="0" step="1" value="{html.escape(min_price)}" placeholder="0" />
          </label>
          <label class="field">Max price (PKR)
            <input type="number" name="max_price" min="0" step="1" value="{html.escape(max_price)}" placeholder="Any" />
          </label>
          <label class="field">Discovered from
            <input type="date" name="start_date" value="{html.escape(start_date)}" />
          </label>
          <label class="field">Discovered to
            <input type="date" name="end_date" value="{html.escape(end_date)}" />
          </label>
          <label class="field">Sort
            <select name="sort">{sort_options}</select>
          </label>
          <div class="btn-row">
            <button type="submit">Apply</button>
            <a href="/" class="btn secondary">Reset</a>
          </div>
        </form>
        """
    )

    if not result["items"]:
        parts.append(
            '<div class="banner">No listings matched the selected filters.</div>'
        )
    else:
        rows_html: List[str] = []
        for item in result["items"]:
            title_txt = html.escape(item.get("title") or "(Untitled)")
            safe_url = item.get("safe_url")
            title_cell = (
                f'<a href="{html.escape(safe_url)}" target="_blank" rel="noopener noreferrer">{title_txt}</a>'
                if safe_url
                else title_txt
            )
            desc = (item.get("description") or "").strip()
            if desc:
                snippet = desc[:160] + ("..." if len(desc) > 160 else "")
                title_cell += f'<div class="desc">{html.escape(snippet)}</div>'

            price_str = html.escape(item.get("price") or "Unknown")
            if item.get("price_numeric") is not None:
                price_sub = f'<div class="desc mono">PKR {int(item["price_numeric"]):,}</div>'
            else:
                price_sub = '<div class="desc">Price unknown</div>'

            city_txt = html.escape((item.get("city") or "Unknown").title())
            loc_txt = html.escape(item.get("location") or "")
            seller_txt = html.escape(item.get("seller_name") or "Unknown")

            disc_date = _format_karachi_date(item.get("discovered_date"))
            src = item.get("discovery_source") or "unknown"
            badge_cls = "ok" if src == "live" else ("warn" if src == "archive" else "")
            src_label = (
                "Archive est." if src == "archive" else ("Live" if src == "live" else "Unknown")
            )
            scraped_txt = html.escape(_format_karachi_dt(item.get("scraped_at")))

            rows_html.append(
                f"""
                <tr>
                  <td>{title_cell}</td>
                  <td class="mono">{price_str}{price_sub}</td>
                  <td>{city_txt}<div class="desc">{loc_txt}</div></td>
                  <td>{seller_txt}</td>
                  <td class="mono">{html.escape(disc_date)}<div><span class="badge {badge_cls}">{src_label}</span></div></td>
                  <td class="mono">{scraped_txt}</td>
                </tr>
                """
            )

        parts.append(
            f"""
            <table>
              <thead>
                <tr>
                  <th>Laptop</th>
                  <th>Price</th>
                  <th>Location</th>
                  <th>Seller</th>
                  <th>Discovered</th>
                  <th>Last Scraped</th>
                </tr>
              </thead>
              <tbody>
                {"".join(rows_html)}
              </tbody>
            </table>
            """
        )

        if result["total_pages"] > 1:
            base_params = {
                "mode": mode,
                "q": q,
                "city": city,
                "min_price": min_price,
                "max_price": max_price,
                "start_date": start_date,
                "end_date": end_date,
                "sort": sort,
            }
            clean_params = {k: v for k, v in base_params.items() if v}
            prev_link = ""
            next_link = ""
            if result["page"] > 1:
                p_qs = urlencode({**clean_params, "page": result["page"] - 1})
                prev_link = f'<a class="btn secondary" href="/?{html.escape(p_qs)}">Previous</a>'
            if result["page"] < result["total_pages"]:
                n_qs = urlencode({**clean_params, "page": result["page"] + 1})
                next_link = f'<a class="btn secondary" href="/?{html.escape(n_qs)}">Next</a>'
            parts.append(
                f'<div class="pager"><div>{prev_link}</div>'
                f'<div class="desc">Page {result["page"]} of {result["total_pages"]}</div>'
                f'<div>{next_link}</div></div>'
            )

    return _page_shell("Listings", "listings", "\n".join(parts))


def _render_stats_section(title: str, stats: Dict[str, Any]) -> str:
    return f"""
    <h3 style="margin: 18px 0 10px 0;">{html.escape(title)}</h3>
    <div class="cards">
      <div class="card">
        <div class="label">Requests (Samples)</div>
        <div class="val mono">{stats['count']}</div>
        <div class="sub">{stats['logical_fetches']} logical fetches, {stats['retries']} retries</div>
      </div>
      <div class="card">
        <div class="label">Average Latency</div>
        <div class="val mono">{html.escape(_format_ms(stats['avg_ms']))}</div>
        <div class="sub">P50 median: {html.escape(_format_ms(stats['p50_ms']))}</div>
      </div>
      <div class="card">
        <div class="label">P95 Latency</div>
        <div class="val mono">{html.escape(_format_ms(stats['p95_ms']))}</div>
        <div class="sub">Max: {html.escape(_format_ms(stats['max_ms']))}</div>
      </div>
      <div class="card">
        <div class="label">P99 (Slowest 1%)</div>
        <div class="val mono">{html.escape(_format_ms(stats['p99_ms']))}</div>
        <div class="sub">Tail 1% HTTP latency</div>
      </div>
      <div class="card">
        <div class="label">P99.9 (Slowest 0.1%)</div>
        <div class="val mono">{html.escape(_format_ms(stats['p999_ms']))}</div>
        <div class="sub">Tail 0.1% HTTP latency</div>
      </div>
      <div class="card">
        <div class="label">Failure Rates</div>
        <div class="val mono">{html.escape(_format_pct(stats['attempt_failure_rate']))}</div>
        <div class="sub">Final fetch failures: {html.escape(_format_pct(stats['final_fetch_failure_rate']))}</div>
      </div>
    </div>
    """


def _render_performance_html(summary: Dict[str, Any]) -> str:
    parts: List[str] = []
    window = summary["window"]

    if summary["validation_error"]:
        parts.append(
            f'<div class="banner err">{html.escape(summary["validation_error"])}</div>'
        )
    if not summary["monitoring_db_exists"]:
        parts.append(
            '<div class="banner warn">Monitoring database is not yet initialized. '
            'Run the scraper once to begin collecting latency and run history.</div>'
        )
    elif summary["latest_completed_run"] is None:
        parts.append(
            '<div class="banner info">Run health: Not yet observed (no completed run recorded yet).</div>'
        )
    elif summary["is_stale"]:
        hrs = summary["hours_since_completed"]
        parts.append(
            f'<div class="banner warn">Stale scraper warning: last completed run was '
            f'{hrs:.1f} hours ago (threshold: {summary["stale_hours_threshold"]:.0f}h).</div>'
        )
    else:
        latest_c = summary["latest_completed_run"]
        parts.append(
            f'<div class="banner info">Latest completed run: '
            f'{html.escape(_format_karachi_dt(latest_c["completed_at"]))} '
            f'({html.escape(latest_c["outcome"] or "unknown")}).</div>'
        )

    win_options = "".join(
        f'<option value="{val}"{" selected" if window == val else ""}>{html.escape(label)}</option>'
        for val, label in (
            ("last_run", "Last run"),
            ("24h", "Last 24 hours"),
            ("7d", "Last 7 days"),
            ("30d", "Last 30 days"),
            ("all", "All time"),
        )
    )
    parts.append(
        f"""
        <form class="filters" method="get" action="/performance" style="grid-template-columns: 240px auto;">
          <label class="field">Performance Window
            <select name="window">{win_options}</select>
          </label>
          <div class="btn-row"><button type="submit">Apply</button></div>
        </form>
        """
    )

    if summary["overall"] is not None:
        parts.append(_render_stats_section("Overall HTTP Performance", summary["overall"]))
        parts.append(
            _render_stats_section(
                "Search Pages", summary["by_page_type"][PAGE_TYPE_SEARCH]
            )
        )
        parts.append(
            _render_stats_section(
                "Detail Pages", summary["by_page_type"][PAGE_TYPE_DETAIL]
            )
        )

    parts.append('<h3 style="margin: 22px 0 10px 0;">Recent Run History</h3>')
    if not summary["recent_runs"]:
        parts.append('<div class="banner">No runs recorded yet.</div>')
    else:
        run_rows: List[str] = []
        for r in summary["recent_runs"]:
            eff = r["effective_outcome"]
            badge_cls = (
                "ok"
                if eff == "completed"
                else ("warn" if eff in ("completed-with-fetch-errors", "incomplete") else "err")
            )
            run_rows.append(
                f"""
                <tr>
                  <td class="mono">{html.escape(_format_karachi_dt(r['started_at']))}</td>
                  <td class="mono">{html.escape(_format_ms(r.get('duration_ms')))}</td>
                  <td><span class="badge {badge_cls}">{html.escape(eff)}</span></td>
                  <td class="mono">{r['listings_seen']}</td>
                  <td class="mono">{r['new_count']}</td>
                  <td class="mono">{r['stored_count']}</td>
                  <td class="mono">{r['repeat_count']}</td>
                  <td class="mono">{r['skipped_count']}</td>
                  <td class="mono">{r['error_count']}</td>
                </tr>
                """
            )
        parts.append(
            f"""
            <table>
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Duration</th>
                  <th>Outcome</th>
                  <th>Seen</th>
                  <th>New</th>
                  <th>Stored</th>
                  <th>Repeat</th>
                  <th>Skipped</th>
                  <th>Errors</th>
                </tr>
              </thead>
              <tbody>{"".join(run_rows)}</tbody>
            </table>
            """
        )

    return _page_shell("Performance", "performance", "\n".join(parts))


def create_app(
    db_path: Optional[str] = None,
    monitoring_db_path: Optional[str] = None,
    *,
    stale_hours: float = 26.0,
) -> FastAPI:
    """Create the read-only FastAPI reporting application."""
    resolved_db = db_path or os.environ.get("OLX_DB_PATH") or config.DEFAULT_DB_PATH
    resolved_mon = (
        monitoring_db_path
        if monitoring_db_path is not None
        else os.environ.get("OLX_MONITORING_DB_PATH") or config.DEFAULT_MONITORING_DB_PATH
    )
    resolved_stale = float(os.environ.get("STALE_HOURS", stale_hours))

    app = FastAPI(title="OLX Laptop Tracker", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "olx_db_exists": os.path.exists(resolved_db),
                "monitoring_db_exists": bool(
                    resolved_mon and os.path.exists(resolved_mon)
                ),
            }
        )

    @app.get("/", response_class=HTMLResponse)
    def listings_page(
        mode: str = Query("discovered_today"),
        q: str = Query(""),
        city: str = Query("all"),
        min_price: str = Query(""),
        max_price: str = Query(""),
        start_date: str = Query(""),
        end_date: str = Query(""),
        sort: str = Query("newest"),
        page: int = Query(1, ge=1),
        page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    ) -> HTMLResponse:
        result = query_listings(
            resolved_db,
            resolved_mon,
            mode=mode,
            q=q,
            city=city,
            min_price=min_price,
            max_price=max_price,
            start_date=start_date,
            end_date=end_date,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        status = 400 if result["validation_error"] else 200
        return HTMLResponse(
            _render_listings_html(
                result,
                q=q,
                city=city,
                min_price=min_price,
                max_price=max_price,
                start_date=start_date,
                end_date=end_date,
            ),
            status_code=status,
        )

    @app.get("/api/listings")
    def listings_api(
        mode: str = Query("discovered_today"),
        q: str = Query(""),
        city: str = Query("all"),
        min_price: str = Query(""),
        max_price: str = Query(""),
        start_date: str = Query(""),
        end_date: str = Query(""),
        sort: str = Query("newest"),
        page: int = Query(1, ge=1),
        page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    ) -> JSONResponse:
        result = query_listings(
            resolved_db,
            resolved_mon,
            mode=mode,
            q=q,
            city=city,
            min_price=min_price,
            max_price=max_price,
            start_date=start_date,
            end_date=end_date,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        status = 400 if result["validation_error"] else 200
        return JSONResponse(result, status_code=status)

    @app.get("/performance", response_class=HTMLResponse)
    def performance_page(window: str = Query("all")) -> HTMLResponse:
        summary = query_performance(
            resolved_mon, window=window, stale_hours=resolved_stale
        )
        status = 400 if summary["validation_error"] else 200
        return HTMLResponse(_render_performance_html(summary), status_code=status)

    @app.get("/api/performance")
    def performance_api(window: str = Query("all")) -> JSONResponse:
        summary = query_performance(
            resolved_mon, window=window, stale_hours=resolved_stale
        )
        status = 400 if summary["validation_error"] else 200
        return JSONResponse(summary, status_code=status)

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.web",
        description="Run the read-only OLX Laptop Tracker Web UI.",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("OLX_DB_PATH", config.DEFAULT_DB_PATH),
        help=f"Path to olx.db (default: {config.DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--monitoring-db",
        default=os.environ.get(
            "OLX_MONITORING_DB_PATH", config.DEFAULT_MONITORING_DB_PATH
        ),
        help=(
            "Path to monitoring.db "
            f"(default: {config.DEFAULT_MONITORING_DB_PATH})."
        ),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("WEB_HOST", "127.0.0.1"),
        help="Host IP to bind inside the process/container (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WEB_PORT", "8000")),
        help="Listening port (default: 8000).",
    )
    parser.add_argument(
        "--stale-hours",
        type=float,
        default=float(os.environ.get("STALE_HOURS", "26")),
        help="Hours after last completed run before showing stale warning (default: 26).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    app = create_app(
        db_path=args.db,
        monitoring_db_path=args.monitoring_db,
        stale_hours=args.stale_hours,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
