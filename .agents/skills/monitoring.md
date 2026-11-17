# Domain Skill: Durable Monitoring

## Purpose

Apply when extending monitoring storage, scraper latency/run instrumentation, or the read-only Web UI. Read the active [SPECS.md](../../SPECS.md) and [reviewer findings](../../REVIEWER_FINDINGS.md) first. [scraper/monitoring.py](../../scraper/monitoring.py) is the durable storage foundation.

---

## Domain Principles

- [Listing storage](../../scraper/storage.py) owns `olx.db`. Preserve its schema, latest-scrape/upsert meaning, and export ordering. [Monitoring storage](../../scraper/monitoring.py) owns `monitoring.db`; monitoring migrations must never target `olx.db`.
- A discovery is the first known encounter of a listing ID. An observation is one processed encounter, including repeats. A run is one scrape execution. HTTP retries are request attempts, not extra listing observations.
- Live first-discovery dates stay immutable. Only explicit `reconcile_archive_discovery` may improve `archive` or `unknown` records.
- Archive counts are lower bounds, not exact live observation totals. Missing scrape timestamps remain `unknown`; `posted_at` is never a substitute.
- Persist UTC timestamps; report start-inclusive/end-exclusive dates in `Asia/Karachi`. The existing fixed-offset fallback has limits recorded in [DEBT-002](../../TECH_DEBT.md).

---

## Required Patterns

- Import historical sources only through explicit operator paths (`python -m scraper.monitoring import ...`). Keep production data out of images, fixtures, and commits.
- Persist run start before work; unfinished runs remain visible. Persist per-attempt `request_events` (excluding sleep/backoff) so exact mean, P50, P95, P99 (slowest 1%), and P99.9 (slowest 0.1%) latencies survive restarts. Keep monitoring DB failures non-fatal to `olx.db` writes and exports.
- Web UI access is strictly read-only (`?mode=ro` + `PRAGMA query_only = ON`) with parameterized SQL queries and no write routes. [connect](../../scraper/monitoring.py) creates/migrates schema and is therefore writer-only.
- Bind the Web UI only to explicitly configured private LAN/Tailscale addresses (no wildcard `0.0.0.0` default); see [DEBT-003](../../TECH_DEBT.md) for the temporary no-auth compromise.

---

## Avoid

- Do not silently turn unknown historical dates into today's date or the ad's `posted_at` date.
- Do not count every repeated archive row as a new observation or mix imported counts into HTTP metrics.
- Do not allow monitoring DB errors to break scraping, or expose unparameterized SQL / write endpoints in the Web UI.
- Do not use SQLite `immutable=1` against the actively written `olx.db` or `monitoring.db`; verify read-only WAL access under container volume permissions.

---

## Blueprint

Explicit operator import through [scraper/monitoring.py](../../scraper/monitoring.py):

```sh
uv run python -m scraper.monitoring --db data/monitoring.db import /operator/archive/listings-2026-10-04.json
uv run python -m scraper.monitoring --db data/monitoring.db stats
```

Read-only Web UI connection pattern; the scraper writer initializes databases separately:

```python
import sqlite3
from pathlib import Path

def open_readonly_db(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn
```

---

## Verification

- [ ] Full synthetic test suite passes, including `REV-001`/`REV-002` invariants, retry/failure latency metrics (mean, P99, P99.9), and non-blocking monitoring failure tests.
- [ ] Listing schema/exports stay unchanged; unfinished runs and empty/missing DB states are truthful.
- [ ] Web UI opens both DBs read-only (`query_only = ON`), handles filters/search safely, and verifies WAL read compatibility in Docker.
- [ ] Private host-bind config, container recreation state retention, and deployment checks are verified or explicitly documented.
