"""Durable, isolated monitoring storage for the OLX scraper.

This module owns the *second* SQLite database, separate from the listing
database in :mod:`scraper.storage`. Keeping monitoring history in its own file
means reporting can never mutate the listing schema, its upsert semantics, or
its export column order.

The model records three distinct things, which the specification requires us to
keep separate:

* **Discoveries** — the first time a listing ID was ever seen. One row per
  ``item_id``; the earliest known timestamp wins and is only ever moved
  *earlier* (never later). Table: ``discoveries``.
* **Observations** — one row per *processed listing encounter*, including
  repeat encounters across pages and runs. Table: ``observations``. Repeats are
  counted; HTTP retries are not (the runner records one observation per listing
  it accepts, not per network attempt).
* **Runs** — the lifecycle of a scrape run: the start is persisted *before*
  work begins and the completion/outcome is recorded after. Unfinished runs stay
  visible via :func:`list_incomplete_runs` rather than being falsely marked
  successful. Table: ``runs``.

Historical daily exports can be imported as *estimates* via
:func:`import_archive`. Imports are idempotent and are never performed
automatically: an operator passes explicit, configurable paths. Production data
is never baked into this module, its tests, or default deployment paths.

All timestamps are stored in UTC as ISO-8601 strings. Calendar dates used for
reporting are computed in ``Asia/Karachi`` (PKT) via :func:`to_karachi_date`,
so day boundaries match the operator's local calendar. When system timezone
data is unavailable, reporting falls back to a fixed ``UTC+05:00`` offset
(valid for post-2009 dates without DST; see ``TECH_DEBT.md`` ``DEBT-002``).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from scraper import config

# Bumped whenever the monitoring schema changes so an operator can tell which
# shape a database is in. Stored in the ``schema_meta`` table.
MONITORING_SCHEMA_VERSION = "2"

# Reporting calendar timezone. Pakistan has observed no DST since 2009, so a
# fixed +05:00 offset matches ``Asia/Karachi`` for current supported dates. We
# prefer the IANA zone when the tz database is available and fall back to the
# fixed offset when tzdata is absent (see TECH_DEBT.md DEBT-002 for older DST
# date limits).
PKT_FIXED_TZ = timezone(timedelta(hours=5), name="PKT")


def resolve_karachi_tz(zoneinfo_cls: Optional[Any] = None) -> Any:
    """Return ``Asia/Karachi`` via zoneinfo, falling back to fixed UTC+05:00."""
    try:
        if zoneinfo_cls is None:
            from zoneinfo import ZoneInfo as zoneinfo_cls
        return zoneinfo_cls("Asia/Karachi")
    except (ImportError, KeyError):  # ZoneInfoNotFoundError subclasses KeyError
        return PKT_FIXED_TZ


KARACHI_TZ = resolve_karachi_tz()

# Observation outcomes. ``stored`` means the listing was successfully written to
# the listing database (partial listings retained after a detail-fetch failure
# still count as stored, matching the scraper's existing behavior). ``failed``
# means the encounter was processed but storage did not succeed; it is counted
# separately so attempted and successful observations stay distinguishable.
OUTCOME_STORED = "stored"
OUTCOME_FAILED = "failed"
VALID_OUTCOMES = (OUTCOME_STORED, OUTCOME_FAILED)

# Observation/discovery provenance.
SOURCE_LIVE = "live"
SOURCE_ARCHIVE = "archive"
SOURCE_UNKNOWN = "unknown"
VALID_DISCOVERY_SOURCES = (SOURCE_LIVE, SOURCE_ARCHIVE, SOURCE_UNKNOWN)

# Run outcomes.
RUN_COMPLETED = "completed"
RUN_COMPLETED_WITH_FETCH_ERRORS = "completed-with-fetch-errors"
RUN_FAILED = "failed"

# HTTP attempt telemetry bounds.
PAGE_TYPE_SEARCH = "search"
PAGE_TYPE_DETAIL = "detail"
VALID_PAGE_TYPES = (PAGE_TYPE_SEARCH, PAGE_TYPE_DETAIL)

ATTEMPT_OK = "ok"
ATTEMPT_TRANSIENT_HTTP = "transient_http"
ATTEMPT_HTTP_ERROR = "http_error"
ATTEMPT_REQUEST_ERROR = "request_error"
VALID_ATTEMPT_OUTCOMES = (
    ATTEMPT_OK,
    ATTEMPT_TRANSIENT_HTTP,
    ATTEMPT_HTTP_ERROR,
    ATTEMPT_REQUEST_ERROR,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Returns ``None`` when the value is empty or unparseable. A trailing ``Z``
    is accepted (Python 3.10's ``fromisoformat`` only understands ``Z`` from
    3.11 onward). Naive timestamps are treated as UTC.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_timestamp(value: Optional[str]) -> Optional[str]:
    """Return a canonical UTC ISO-8601 string, or ``None`` if unparseable."""
    parsed = parse_timestamp(value)
    return parsed.isoformat() if parsed else None


def to_karachi_date(value: str, *, tz: Optional[Any] = None) -> str:
    """Return the ``Asia/Karachi`` calendar date (``YYYY-MM-DD``) of a timestamp.

    Raises ``ValueError`` when the timestamp cannot be parsed, so callers never
    silently bucket an observation under a wrong day.
    """
    parsed = parse_timestamp(value)
    if parsed is None:
        raise ValueError(f"Unparseable timestamp: {value!r}")
    target_tz = tz if tz is not None else KARACHI_TZ
    return parsed.astimezone(target_tz).date().isoformat()


# ---------------------------------------------------------------------------
# Connection and schema
# ---------------------------------------------------------------------------


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating if needed) the monitoring database and ensure the schema."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # WAL lets the exporter/snapshot publisher read while the scraper writes,
    # without blocking either side.
    conn.execute("PRAGMA journal_mode = WAL")
    _create_schema(conn)
    _migrate(conn)
    return conn


def open_readonly_db(path: str, *, timeout: float = 5.0) -> sqlite3.Connection:
    """Open an existing SQLite database strictly read-only.

    Never creates or migrates schema and enforces ``PRAGMA query_only = ON``.
    """
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the monitoring tables if they do not already exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discoveries (
            item_id          TEXT PRIMARY KEY,
            discovered_at    TEXT,                 -- UTC ISO-8601; NULL = unknown
            discovered_date  TEXT,                 -- Asia/Karachi calendar date
            discovery_source TEXT NOT NULL,        -- live | archive | unknown
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS observations (
            observation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id         TEXT NOT NULL,
            observed_at     TEXT NOT NULL,         -- UTC ISO-8601
            observed_date   TEXT NOT NULL,         -- Asia/Karachi calendar date
            outcome         TEXT NOT NULL,         -- stored | failed
            source          TEXT NOT NULL,         -- live | archive
            run_id          TEXT,
            city            TEXT,
            idempotency_key TEXT UNIQUE            -- set for archive imports; NULL for live
        );
        CREATE INDEX IF NOT EXISTS idx_observations_item
            ON observations(item_id);
        CREATE INDEX IF NOT EXISTS idx_observations_date
            ON observations(observed_date);
        CREATE INDEX IF NOT EXISTS idx_observations_run
            ON observations(run_id);

        CREATE TABLE IF NOT EXISTS runs (
            run_id        TEXT PRIMARY KEY,
            started_at    TEXT NOT NULL,
            started_date  TEXT NOT NULL,
            completed_at  TEXT,                    -- NULL while running / abandoned
            outcome       TEXT,                    -- NULL until finished
            duration_ms   REAL,                    -- monotonic total run duration
            listings_seen INTEGER NOT NULL DEFAULT 0,
            new_count     INTEGER NOT NULL DEFAULT 0,
            stored_count  INTEGER NOT NULL DEFAULT 0,
            repeat_count  INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            error_count   INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS request_events (
            event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         TEXT,
            recorded_at    TEXT NOT NULL,          -- UTC ISO-8601
            recorded_date  TEXT NOT NULL,          -- Asia/Karachi calendar date
            page_type      TEXT NOT NULL,          -- search | detail
            city           TEXT,
            attempt_number INTEGER NOT NULL,       -- 1-based attempt index
            status_code    INTEGER,                -- NULL on network/request error
            outcome        TEXT NOT NULL,          -- ok | transient_http | http_error | request_error
            is_final       INTEGER NOT NULL DEFAULT 0,
            duration_ms    REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_request_events_recorded
            ON request_events(recorded_at);
        CREATE INDEX IF NOT EXISTS idx_request_events_run
            ON request_events(run_id);

        CREATE TABLE IF NOT EXISTS archive_imports (
            import_id     TEXT PRIMARY KEY,
            source_path   TEXT NOT NULL,
            source_kind   TEXT NOT NULL,           -- json | csv
            imported_at   TEXT NOT NULL,
            rows_seen     INTEGER NOT NULL DEFAULT 0,
            rows_imported INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS counters (
            name       TEXT PRIMARY KEY,
            value      REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schema_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """Add ``column`` to ``table`` if it does not already exist.

    Mirrors the conservative migration pattern used by the listing storage:
    inspect ``PRAGMA table_info`` and only run ``ALTER TABLE ... ADD COLUMN``
    when the column is missing. It is a no-op for current databases.
    """
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an older monitoring database up to the current schema.

    Only monitoring tables are touched here; the listing database is owned by
    :mod:`scraper.storage` and is never modified by this module.
    """
    _ensure_column(conn, "discoveries", "discovered_date", "TEXT")
    _ensure_column(conn, "runs", "duration_ms", "REAL")
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (MONITORING_SCHEMA_VERSION,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Discovery records (immutable; archive reconciliation may only move earlier)
# ---------------------------------------------------------------------------


def record_discovery(
    conn: sqlite3.Connection,
    item_id: Optional[str],
    discovered_at: Optional[str] = None,
    *,
    source: str = SOURCE_LIVE,
    allow_archive_reconcile: bool = False,
) -> bool:
    """Record (or explicitly reconcile) the first-discovery time of a listing ID.

    Returns ``True`` when a row was inserted or an eligible archived/unknown
    estimate was improved. It is idempotent: replaying the same timestamp
    returns ``False`` and changes nothing.

    Rules required by the specification:

    * Established ``live`` discovery records are immutable.
    * ``unknown`` baseline records are never recategorized as ``live``
      discoveries on encounter; only explicit permitted archive reconciliation
      with a valid scrape timestamp may populate them.
    * Explicit archive reconciliation (``allow_archive_reconcile=True`` with
      ``source=SOURCE_ARCHIVE``) may replace an ``archive`` estimate only with
      an *earlier* archived time.
    * A listing with no recoverable date is stored with ``discovered_at`` NULL
      and source ``unknown`` so it still counts in all-time totals (but not in
      date-range queries).
    """
    if source not in VALID_DISCOVERY_SOURCES:
        raise ValueError(
            f"Invalid discovery source {source!r}; "
            f"expected one of {VALID_DISCOVERY_SOURCES}"
        )
    if not item_id:
        return False

    now = _utcnow_iso()
    new_dt = parse_timestamp(discovered_at)
    new_date = (
        new_dt.astimezone(KARACHI_TZ).date().isoformat() if new_dt else None
    )

    existing = conn.execute(
        "SELECT discovered_at, discovery_source FROM discoveries WHERE item_id = ?",
        (item_id,),
    ).fetchone()

    if existing is None:
        stored_source = source if new_dt is not None else SOURCE_UNKNOWN
        conn.execute(
            """
            INSERT INTO discoveries
                (item_id, discovered_at, discovered_date, discovery_source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item_id,
                new_dt.isoformat() if new_dt else None,
                new_date,
                stored_source,
                now,
            ),
        )
        conn.commit()
        return True

    # Established live records are strictly immutable, and non-reconciliation
    # calls (including repeat live ingestion on unknown baselines) never
    # overwrite an existing discovery row.
    if not (allow_archive_reconcile and source == SOURCE_ARCHIVE):
        return False

    if new_dt is None:
        # Nothing to improve; never overwrite a known date with "unknown".
        return False

    existing_source = existing["discovery_source"]
    if existing_source not in (SOURCE_ARCHIVE, SOURCE_UNKNOWN):
        return False

    old_dt = parse_timestamp(existing["discovered_at"])
    if old_dt is None or new_dt < old_dt:
        conn.execute(
            """
            UPDATE discoveries
               SET discovered_at = ?, discovered_date = ?,
                   discovery_source = ?, updated_at = ?
             WHERE item_id = ?
            """,
            (new_dt.isoformat(), new_date, SOURCE_ARCHIVE, now, item_id),
        )
        conn.commit()
        return True

    return False


def reconcile_archive_discovery(
    conn: sqlite3.Connection,
    item_id: Optional[str],
    discovered_at: Optional[str] = None,
) -> bool:
    """Explicitly reconcile a discovery record from a retained archive.

    Inserts unseen IDs (as ``archive`` when a valid scrape timestamp exists, or
    ``unknown`` otherwise), fills ``unknown`` baseline rows when an archive
    provides a valid scrape time, and moves ``archive`` estimates earlier
    idempotently. Never modifies established ``live`` discoveries.
    """
    return record_discovery(
        conn,
        item_id,
        discovered_at,
        source=SOURCE_ARCHIVE,
        allow_archive_reconcile=True,
    )


# ---------------------------------------------------------------------------
# Observation records
# ---------------------------------------------------------------------------


def record_observation(
    conn: sqlite3.Connection,
    item_id: str,
    observed_at: Optional[str] = None,
    *,
    outcome: str = OUTCOME_STORED,
    source: str = SOURCE_LIVE,
    run_id: Optional[str] = None,
    city: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Optional[int]:
    """Record one processed listing encounter and return its observation ID.

    Returns ``None`` when an observation with the same ``idempotency_key``
    already exists (an idempotent no-op). The key is used by archive imports so
    repeated cumulative snapshots containing the same ID/timestamp pair do not
    inflate counts. Live observations pass no key.

    ``outcome`` must be one of :data:`VALID_OUTCOMES`; this separates
    successfully stored observations from attempts whose storage failed.
    """
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"Invalid observation outcome {outcome!r}; "
            f"expected one of {VALID_OUTCOMES}"
        )

    normalized = _normalize_timestamp(observed_at) or _utcnow_iso()
    observed_date = to_karachi_date(normalized)

    if idempotency_key is not None:
        existing = conn.execute(
            "SELECT observation_id FROM observations WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return None

    cursor = conn.execute(
        """
        INSERT INTO observations
            (item_id, observed_at, observed_date, outcome, source,
             run_id, city, idempotency_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            normalized,
            observed_date,
            outcome,
            source,
            run_id,
            city,
            idempotency_key,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


def start_run(
    conn: sqlite3.Connection,
    run_id: Optional[str] = None,
    started_at: Optional[str] = None,
) -> str:
    """Persist the start of a run *before* any work happens and return its ID.

    The row is committed immediately so an abrupt process death leaves an
    unfinished run visible (``completed_at`` NULL) instead of the run vanishing.
    """
    started = _normalize_timestamp(started_at) or _utcnow_iso()
    resolved_id = run_id or f"run-{started}"
    conn.execute(
        """
        INSERT OR IGNORE INTO runs (run_id, started_at, started_date)
        VALUES (?, ?, ?)
        """,
        (resolved_id, started, to_karachi_date(started)),
    )
    conn.commit()
    return resolved_id


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    outcome: str,
    completed_at: Optional[str] = None,
    duration_ms: Optional[float] = None,
    listings_seen: Optional[int] = None,
    new_count: Optional[int] = None,
    stored_count: Optional[int] = None,
    repeat_count: Optional[int] = None,
    skipped_count: Optional[int] = None,
    error_count: Optional[int] = None,
) -> None:
    """Record a run's completion, outcome, and (optional) counters."""
    values: Dict[str, Any] = {
        "completed_at": _normalize_timestamp(completed_at) or _utcnow_iso(),
        "outcome": outcome,
    }
    if duration_ms is not None:
        values["duration_ms"] = float(duration_ms)
    for column, value in (
        ("listings_seen", listings_seen),
        ("new_count", new_count),
        ("stored_count", stored_count),
        ("repeat_count", repeat_count),
        ("skipped_count", skipped_count),
        ("error_count", error_count),
    ):
        if value is not None:
            values[column] = int(value)

    assignments = ", ".join(f"{column} = ?" for column in values)
    conn.execute(
        f"UPDATE runs SET {assignments} WHERE run_id = ?",
        list(values.values()) + [run_id],
    )
    conn.commit()


def list_incomplete_runs(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Return runs that were started but never marked complete.

    These are surfaced (not silently succeeded) so the exporter can report
    unfinished/abandoned work truthfully.
    """
    rows = conn.execute(
        """
        SELECT run_id, started_at, started_date
          FROM runs
         WHERE completed_at IS NULL
      ORDER BY started_at
        """
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Per-attempt HTTP latency & failure telemetry
# ---------------------------------------------------------------------------


def record_request_event(
    conn: sqlite3.Connection,
    *,
    page_type: str,
    outcome: str,
    duration_ms: float,
    attempt_number: int = 1,
    is_final: bool = True,
    status_code: Optional[int] = None,
    city: Optional[str] = None,
    run_id: Optional[str] = None,
    recorded_at: Optional[str] = None,
) -> int:
    """Persist one HTTP request attempt for latency and failure reporting.

    Each row is committed immediately so completed request work survives abrupt
    process termination. Excludes politeness sleeps and retry backoffs.
    """
    if page_type not in VALID_PAGE_TYPES:
        raise ValueError(
            f"Invalid page_type {page_type!r}; expected one of {VALID_PAGE_TYPES}"
        )
    if outcome not in VALID_ATTEMPT_OUTCOMES:
        raise ValueError(
            f"Invalid attempt outcome {outcome!r}; "
            f"expected one of {VALID_ATTEMPT_OUTCOMES}"
        )
    if attempt_number < 1:
        raise ValueError("attempt_number must be >= 1")
    if duration_ms < 0:
        raise ValueError("duration_ms must be >= 0")

    recorded = _normalize_timestamp(recorded_at) or _utcnow_iso()
    recorded_date = to_karachi_date(recorded)
    cursor = conn.execute(
        """
        INSERT INTO request_events
            (run_id, recorded_at, recorded_date, page_type, city,
             attempt_number, status_code, outcome, is_final, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            recorded,
            recorded_date,
            page_type,
            city,
            int(attempt_number),
            int(status_code) if status_code is not None else None,
            outcome,
            1 if is_final else 0,
            float(duration_ms),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def compute_percentile(
    sorted_values: List[float], quantile: float
) -> Optional[float]:
    """Compute an exact linear-interpolated percentile over sorted values.

    ``quantile`` is in ``[0.0, 1.0]`` (e.g. ``0.99`` for P99 / slowest 1%,
    ``0.999`` for P99.9 / slowest 0.1%). Returns ``None`` when empty.
    """
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return float(sorted_values[0])
    pos = quantile * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo]))


def compute_latency_stats(durations_ms: List[float]) -> Dict[str, Any]:
    """Return sample count, average, min/max, P50, P95, P99, and P99.9."""
    if not durations_ms:
        return {
            "count": 0,
            "avg_ms": None,
            "min_ms": None,
            "max_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "p999_ms": None,
        }
    ordered = sorted(float(v) for v in durations_ms)
    return {
        "count": len(ordered),
        "avg_ms": sum(ordered) / len(ordered),
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        "p50_ms": compute_percentile(ordered, 0.50),
        "p95_ms": compute_percentile(ordered, 0.95),
        "p99_ms": compute_percentile(ordered, 0.99),
        "p999_ms": compute_percentile(ordered, 0.999),
    }


def _summarize_attempt_rows(rows: List[sqlite3.Row]) -> Dict[str, Any]:
    """Aggregate latency percentiles and attempt/final failure rates."""
    durations = [float(r["duration_ms"]) for r in rows]
    stats = compute_latency_stats(durations)
    total_attempts = len(rows)
    failed_attempts = sum(1 for r in rows if r["outcome"] != ATTEMPT_OK)
    retries = sum(1 for r in rows if int(r["attempt_number"]) > 1)
    final_rows = [r for r in rows if int(r["is_final"]) == 1]
    logical_fetches = len(final_rows)
    final_failures = sum(1 for r in final_rows if r["outcome"] != ATTEMPT_OK)

    stats.update(
        {
            "total_attempts": total_attempts,
            "failed_attempts": failed_attempts,
            "attempt_failure_rate": (
                failed_attempts / total_attempts if total_attempts else None
            ),
            "logical_fetches": logical_fetches,
            "final_failures": final_failures,
            "final_fetch_failure_rate": (
                final_failures / logical_fetches if logical_fetches else None
            ),
            "retries": retries,
        }
    )
    return stats


VALID_PERFORMANCE_WINDOWS = ("last_run", "24h", "7d", "30d", "all")


def get_performance_summary(
    conn: sqlite3.Connection,
    *,
    window: str = "all",
    now_utc: Optional[datetime] = None,
    stale_hours: float = 26.0,
    run_limit: int = 20,
) -> Dict[str, Any]:
    """Compute latency, failure/retry rates, and run health for a window."""
    if window not in VALID_PERFORMANCE_WINDOWS:
        raise ValueError(
            f"Invalid window {window!r}; expected one of {VALID_PERFORMANCE_WINDOWS}"
        )

    now = now_utc.astimezone(timezone.utc) if now_utc else datetime.now(timezone.utc)

    runs_rows = conn.execute(
        """
        SELECT run_id, started_at, started_date, completed_at, outcome,
               duration_ms, listings_seen, new_count, stored_count,
               repeat_count, skipped_count, error_count
          FROM runs
      ORDER BY started_at DESC, rowid DESC
         LIMIT ?
        """,
        (int(run_limit),),
    ).fetchall()
    recent_runs = []
    for row in runs_rows:
        item = dict(row)
        item["effective_outcome"] = item["outcome"] or "incomplete"
        recent_runs.append(item)

    latest_run = recent_runs[0] if recent_runs else None
    latest_completed_row = conn.execute(
        """
        SELECT run_id, started_at, started_date, completed_at, outcome,
               duration_ms, listings_seen, new_count, stored_count,
               repeat_count, skipped_count, error_count
          FROM runs
         WHERE completed_at IS NOT NULL
      ORDER BY completed_at DESC, rowid DESC
         LIMIT 1
        """
    ).fetchone()
    latest_completed_run = dict(latest_completed_row) if latest_completed_row else None

    latest_success_row = conn.execute(
        """
        SELECT run_id, started_at, started_date, completed_at, outcome,
               duration_ms, listings_seen, new_count, stored_count,
               repeat_count, skipped_count, error_count
          FROM runs
         WHERE outcome = ?
      ORDER BY completed_at DESC, rowid DESC
         LIMIT 1
        """,
        (RUN_COMPLETED,),
    ).fetchone()
    latest_successful_run = dict(latest_success_row) if latest_success_row else None

    hours_since_completed: Optional[float] = None
    is_stale = False
    if latest_completed_run is not None:
        completed_dt = parse_timestamp(latest_completed_run["completed_at"])
        if completed_dt is not None:
            hours_since_completed = max(
                0.0, (now - completed_dt).total_seconds() / 3600.0
            )
            is_stale = hours_since_completed > stale_hours

    clauses: List[str] = []
    params: List[Any] = []
    selected_run_id: Optional[str] = None
    if window == "last_run":
        if latest_run is None:
            event_rows: List[sqlite3.Row] = []
        else:
            selected_run_id = latest_run["run_id"]
            clauses.append("run_id = ?")
            params.append(selected_run_id)
            event_rows = conn.execute(
                "SELECT page_type, attempt_number, outcome, is_final, duration_ms "
                "FROM request_events WHERE run_id = ?",
                params,
            ).fetchall()
    else:
        if window == "24h":
            cutoff = (now - timedelta(hours=24)).isoformat()
            clauses.append("recorded_at >= ?")
            params.append(cutoff)
        elif window == "7d":
            cutoff = (now - timedelta(days=7)).isoformat()
            clauses.append("recorded_at >= ?")
            params.append(cutoff)
        elif window == "30d":
            cutoff = (now - timedelta(days=30)).isoformat()
            clauses.append("recorded_at >= ?")
            params.append(cutoff)

        sql = (
            "SELECT page_type, attempt_number, outcome, is_final, duration_ms "
            "FROM request_events"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        event_rows = conn.execute(sql, params).fetchall()

    overall = _summarize_attempt_rows(event_rows)
    by_page_type = {
        pt: _summarize_attempt_rows([r for r in event_rows if r["page_type"] == pt])
        for pt in VALID_PAGE_TYPES
    }

    return {
        "window": window,
        "selected_run_id": selected_run_id,
        "overall": overall,
        "by_page_type": by_page_type,
        "recent_runs": recent_runs,
        "latest_run": latest_run,
        "latest_completed_run": latest_completed_run,
        "latest_successful_run": latest_successful_run,
        "hours_since_completed": hours_since_completed,
        "stale_hours_threshold": stale_hours,
        "is_stale": is_stale,
    }


# ---------------------------------------------------------------------------
# Cumulative counters (durable across scraper/exporter restarts)
# ---------------------------------------------------------------------------


def increment_counter(
    conn: sqlite3.Connection, name: str, delta: float = 1.0
) -> float:
    """Atomically add ``delta`` to a durable cumulative counter and return it.

    Counters live in SQLite so they survive scraper *and* exporter restarts and
    are never replayed when observed repeatedly by Prometheus.
    """
    conn.execute(
        """
        INSERT INTO counters (name, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE
            SET value = counters.value + excluded.value,
                updated_at = excluded.updated_at
        """,
        (name, float(delta), _utcnow_iso()),
    )
    conn.commit()
    return get_counter(conn, name)


def get_counter(conn: sqlite3.Connection, name: str) -> float:
    """Return the current value of a counter (0.0 when it has never been set)."""
    row = conn.execute(
        "SELECT value FROM counters WHERE name = ?", (name,)
    ).fetchone()
    return float(row["value"]) if row else 0.0


def get_counters(conn: sqlite3.Connection) -> Dict[str, float]:
    """Return every durable counter as a ``{name: value}`` mapping."""
    rows = conn.execute("SELECT name, value FROM counters").fetchall()
    return {row["name"]: float(row["value"]) for row in rows}


# ---------------------------------------------------------------------------
# Historical archive import (explicit operator action; idempotent)
# ---------------------------------------------------------------------------


def _kind_from_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return "json"
    if ext == ".csv":
        return "csv"
    raise ValueError(f"Unsupported archive extension {ext!r} for {path!r}")


def _read_archive_rows(raw: bytes, kind: str) -> List[Dict[str, Any]]:
    if kind == "json":
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        if isinstance(data, dict):
            data = data.get("listings", [])
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]
    if kind == "csv":
        text = raw.decode("utf-8-sig")
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    raise ValueError(f"Unsupported archive kind {kind!r}")


def _archive_import_id(kind: str, raw: bytes) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    return f"{kind}:{digest}"


def import_archive(
    conn: sqlite3.Connection,
    path: str,
    *,
    source_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Import one historical daily export as reconstructed estimates.

    Each listing contributes:

    * a **discovery** estimate dated by its earliest retained scrape timestamp
      (reconciliation only moves it earlier), and
    * a **lower-bound archive observation** keyed by ``(item_id, timestamp)`` so
      repeated cumulative snapshot rows never inflate counts.

    The import itself is idempotent: re-importing identical file content is a
    no-op keyed on a content digest. The source file is opened read-only and its
    path is passed explicitly by the operator — production data is never
    embedded or assumed.

    Returns a summary dict with ``rows_seen``, ``discoveries_changed``,
    ``observations_added``, ``missing_scrape_times``, and ``duplicate``.
    """
    with open(path, "rb") as handle:
        raw = handle.read()

    kind = source_kind or _kind_from_path(path)
    import_id = _archive_import_id(kind, raw)

    already = conn.execute(
        "SELECT 1 FROM archive_imports WHERE import_id = ?", (import_id,)
    ).fetchone()
    if already is not None:
        return {
            "rows_seen": 0,
            "discoveries_changed": 0,
            "observations_added": 0,
            "missing_scrape_times": 0,
            "duplicate": True,
        }

    rows = _read_archive_rows(raw, kind)
    discoveries_changed = 0
    observations_added = 0
    missing_scrape_times = 0

    for row in rows:
        item_id = row.get("item_id")
        if not item_id:
            continue
        # Never fall back to posted_at: posting time does not prove when the
        # scraper encountered the listing.
        timestamp = _normalize_timestamp(row.get("scraped_at"))
        if timestamp is None:
            missing_scrape_times += 1
        if reconcile_archive_discovery(conn, str(item_id), timestamp):
            discoveries_changed += 1
        if timestamp:
            observation_id = record_observation(
                conn,
                str(item_id),
                timestamp,
                outcome=OUTCOME_STORED,
                source=SOURCE_ARCHIVE,
                idempotency_key=f"archive:{item_id}:{timestamp}",
            )
            if observation_id is not None:
                observations_added += 1

    conn.execute(
        """
        INSERT INTO archive_imports
            (import_id, source_path, source_kind, imported_at,
             rows_seen, rows_imported)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            import_id,
            os.path.abspath(path),
            kind,
            _utcnow_iso(),
            len(rows),
            observations_added,
        ),
    )
    conn.commit()

    return {
        "rows_seen": len(rows),
        "discoveries_changed": discoveries_changed,
        "observations_added": observations_added,
        "missing_scrape_times": missing_scrape_times,
        "duplicate": False,
    }


# ---------------------------------------------------------------------------
# Exact business counts (from persisted records, not Prometheus estimates)
# ---------------------------------------------------------------------------


def count_unique_listings(conn: sqlite3.Connection) -> int:
    """Return the all-time count of distinct listing IDs ever discovered.

    Includes baseline listings whose discovery date is unknown; those are only
    excluded from date-range queries.
    """
    row = conn.execute("SELECT COUNT(*) AS n FROM discoveries").fetchone()
    return int(row["n"]) if row else 0


def count_unknown_discoveries(conn: sqlite3.Connection) -> int:
    """Return the count of discovered listings whose discovery date is unknown."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM discoveries WHERE discovered_at IS NULL"
    ).fetchone()
    return int(row["n"]) if row else 0


def count_discoveries(
    conn: sqlite3.Connection,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """Count discoveries whose Karachi calendar date is in ``[start, end)``.

    Both bounds are optional and start-inclusive / end-exclusive. Listings with
    an unknown discovery date are excluded from any bounded range.
    """
    sql = "SELECT COUNT(*) AS n FROM discoveries"
    clauses: List[str] = []
    params: List[str] = []
    if start_date:
        clauses.append("discovered_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("discovered_date < ?")
        params.append(end_date)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    row = conn.execute(sql, params).fetchone()
    return int(row["n"]) if row else 0


def count_observations(
    conn: sqlite3.Connection,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    outcome: Optional[str] = None,
    source: Optional[str] = None,
) -> int:
    """Count observations whose Karachi date is in ``[start, end)``.

    Optional ``outcome`` and ``source`` filters keep attempted observations
    distinguishable from successfully stored ones, and imported archive
    observations distinguishable from live ones.
    """
    sql = "SELECT COUNT(*) AS n FROM observations"
    clauses: List[str] = []
    params: List[str] = []
    if start_date:
        clauses.append("observed_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("observed_date < ?")
        params.append(end_date)
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    row = conn.execute(sql, params).fetchone()
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# Operator CLI (``python -m scraper.monitoring ...``)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.monitoring",
        description=(
            "Inspect and populate the OLX monitoring database. Calendar dates "
            "use Asia/Karachi (with a fixed UTC+05:00 fallback when tzdata is "
            "unavailable; valid for post-2009 dates without DST)."
        ),
    )
    parser.add_argument(
        "--db",
        default=config.DEFAULT_MONITORING_DB_PATH,
        help="Path to the monitoring SQLite database "
        f"(default: {config.DEFAULT_MONITORING_DB_PATH}).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    importer = subparsers.add_parser(
        "import",
        help="Import historical daily exports as discovery/observation estimates.",
    )
    importer.add_argument(
        "paths",
        nargs="+",
        help="Explicit paths to listings-YYYY-MM-DD.json / .csv exports.",
    )

    subparsers.add_parser(
        "stats", help="Print discovery and observation totals."
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    conn = connect(args.db)
    try:
        if args.command == "import":
            for path in args.paths:
                result = import_archive(conn, path)
                print(
                    f"{path}: seen={result['rows_seen']} "
                    f"new_discoveries={result['discoveries_changed']} "
                    f"new_observations={result['observations_added']} "
                    f"missing_scrape_times={result['missing_scrape_times']} "
                    f"duplicate={result['duplicate']}"
                )
            return 0
        if args.command == "stats":
            today = datetime.now(KARACHI_TZ).date().isoformat()
            print(f"Unique listings (all-time): {count_unique_listings(conn)}")
            print(
                "Unknown discovery dates: "
                f"{count_unknown_discoveries(conn)}"
            )
            print(f"Discoveries today: {count_discoveries(conn, start_date=today)}")
            print(f"Observations today: {count_observations(conn, start_date=today)}")
            print(
                "Archive observations (all-time): "
                f"{count_observations(conn, source=SOURCE_ARCHIVE)}"
            )
            return 0
    finally:
        conn.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
