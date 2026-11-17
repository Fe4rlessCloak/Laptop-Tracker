# Domain Skill: Durable Monitoring

## Purpose

Apply when extending monitoring storage, instrumentation, the exporter, reporting snapshots, or dashboards. Read the active [SPECS.md](../../SPECS.md) and [reviewer findings](../../REVIEWER_FINDINGS.md) first. [scraper/monitoring.py](../../scraper/monitoring.py) is the current foundation, not proof that every required contract is implemented.

---

## Domain Principles

- [Listing storage](../../scraper/storage.py) owns the listing database. Preserve its schema, latest-scrape/upsert meaning, and export ordering. [Monitoring storage](../../scraper/monitoring.py) owns separate durable history; monitoring migrations must never target the listing database.
- A discovery is the first known encounter of a listing ID. An observation is one processed encounter, including repeats. A run is one scrape execution. HTTP retries are request attempts, not extra listing observations.
- Live first-discovery dates stay immutable. Only explicit archive reconciliation allowed by the active spec may improve estimates; a helper accepting an earlier timestamp is not sufficient authorization.
- Archive counts are lower bounds, not exact live observation totals. Missing scrape timestamps remain unknown; posting timestamps are not substitutes.
- Persist UTC timestamps; report start-inclusive/end-exclusive dates in Asia/Karachi. The existing fixed-offset fallback has limits recorded in [DEBT-002](../../TECH_DEBT.md).

---

## Required Patterns

- Import historical sources only through explicit operator paths. Keep sources read-only and production data out of images, fixtures, and commits. Content hashes identify repeated files; normalized listing ID/scrape-time pairs deduplicate observations across cumulative exports and CSV/JSON counterparts.
- Persist run start before work; unfinished runs remain visible. Durable request counters/histograms must survive restarts and be read, not incremented, by the exporter. Bound labels; never use listing IDs, URLs, or exception text as metric labels.
- Exporter access is read-only. The current [connect helper](../../scraper/monitoring.py:139) creates/migrates schema and is therefore not a read-only reader API.
- Snapshot publication must use consistent database reads, integrity checks, atomic replacement, and the common committed watermark/recovery contract from the active spec. Separate listing and monitoring commits are not a cross-database transaction.
- Check external tools before the work that uses them. Operator secrets/addresses gate deployment verification, not synthetic foundation tests. Preserve login, private binds, plugin restrictions, and least-privilege mounts.

---

## Avoid

- Do not silently turn unknown historical dates into today's date or the ad's posting date.
- Do not count every repeated archive row as a new observation or mix imported counts into HTTP metrics.
- Do not copy a live database file directly, publish half-written snapshots, or claim snapshot freshness from scrape success alone.
- Do not promote unverified implementation quirks into the contract. Resolve in-scope reviewer findings before building consumers.

---

## Blueprint

Explicit operator import through the existing [entry point](../../scraper/monitoring.py:762), using synthetic or operator-supplied source paths:

```sh
uv run python -m scraper.monitoring --db data/monitoring.db import /operator/archive/listings-2026-10-04.json
uv run python -m scraper.monitoring --db data/monitoring.db stats
```

Read-only exporter connection pattern; the writer must initialize the database separately:

```python
import sqlite3
from pathlib import Path

def open_monitoring_reader(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn
```

Do not use immutable mode against the actively written monitoring database. Verify read-only WAL access with the actual deployment permissions.

---

## Verification

- [ ] Full synthetic test suite passes, including missing scrape times, immutable live discovery dates, repeated imports, unknown history, and timezone fallback boundaries.
- [ ] Listing schema/exports stay unchanged; failed storage and unfinished runs are truthful.
- [ ] Exporter reads without writing; request aggregates survive repeated reads/restarts without replay.
- [ ] Snapshot watermark, atomic replacement, last-good preservation, and actual plugin refresh are verified when implemented.
- [ ] Runtime secrets, private access, permissions, version checks, and deployment evidence meet the active spec; unavailable checks are reported explicitly.
