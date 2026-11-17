# Architectural Audit Findings

Generated from a code review or architectural audit. The implementation agent should read this file before beginning work and resolve all `Pending` findings that are in scope. When a finding is resolved, the implementation agent marks its `Status` as `Resolved` and adds a note explaining how — it does not edit the finding's problem, severity, or required-action content.

---

## Audit

- **Date:** 2026-10-04
- **Reviewer:** Repository Evolution
- **Repository Revision:** Current working tree; Unit 1 foundation is uncommitted.

---

## Summary

| ID | Severity | Status | File(s) |
|----|----------|--------|---------|
| REV-001 | High | Resolved | [scraper/monitoring.py](scraper/monitoring.py:604) |
| REV-002 | High | Resolved | [scraper/monitoring.py](scraper/monitoring.py:288) |

---

## Findings

### REV-001 — Posting time substituted for historical encounter time

- **Severity:** High
- **Status:** Resolved
- **Files:** [scraper/monitoring.py](scraper/monitoring.py:604)
- **Rule Violated:** [SPECS.md](SPECS.md) — Historical Data and Schema Boundary; discovery and observation dates must not be posting dates.
- **Resolution:** Updated `import_archive` in [scraper/monitoring.py](scraper/monitoring.py) to read `scraped_at` only (never `posted_at`), keep rows without valid scrape times as `unknown` discoveries with zero archive observations, and return/print `missing_scrape_times` coverage counts. Added regression tests in [tests/test_monitoring.py](tests/test_monitoring.py).

#### Problem

The archive importer falls back to posting time when scrape time is absent, then records that value as a discovery estimate and stored archive observation. The ad's posting time does not prove the scraper encountered it then.

#### Why It Matters

This invents historical observation dates and makes discovery-date reports misleading. The existing missing-timestamp test does not cover a row with only posting time.

#### Required Action

Use valid retained scrape timestamps only for archive encounter reconstruction. Missing/unusable scrape times must retain unknown discovery dates, add no archive observation, and be reported in import coverage/results. Do not modify source exports or listing schema.

#### Verification

Add synthetic regression tests for posting-only and invalid-scrape/valid-posting rows: all-time IDs remain counted, bounded discovery counts exclude unknown dates, and no archive observation is invented. Verify repeat imports remain safe and the full suite passes.

---

### REV-002 — Discovery changes are not restricted to approved archive reconciliation

- **Severity:** High
- **Status:** Resolved
- **Files:** [scraper/monitoring.py](scraper/monitoring.py:288), [tests/test_monitoring.py](tests/test_monitoring.py:148)
- **Rule Violated:** [SPECS.md](SPECS.md) — Historical Data and Schema Boundary; established first-discovery records are immutable except explicit permitted archive reconciliation.
- **Resolution:** Updated `record_discovery` in [scraper/monitoring.py](scraper/monitoring.py) to inspect `discovery_source`, keep `live` discoveries strictly immutable, preserve `unknown` baselines against repeat `live` ingestion, and restrict archive updates to explicit `reconcile_archive_discovery` (`allow_archive_reconcile=True`). Fixed the contradictory test and added regression tests in [tests/test_monitoring.py](tests/test_monitoring.py).

#### Problem

The discovery helper reads only the existing timestamp, then accepts any earlier supplied time and replaces its source. It cannot distinguish immutable live records from archived estimates. The existing test explicitly permits replacing a live discovery with an archive date, contrary to the stated exception for archived estimates.

#### Why It Matters

Later ingestion or import calls can silently rewrite established discovery history and its origin. Unknown baseline dates must also not be recategorized as new live discoveries on deployment.

#### Required Action

Enforce the existing spec's distinction between live records, archived estimates, and unknown baseline records. Keep established live dates immutable; improve archived estimates only through explicit permitted archive reconciliation. Preserve unknown baseline history unless a retained archive provides a valid discovery estimate. Update the contradictory test and add regression tests before fixes.

#### Verification

Tests prove earlier live calls and archive calls do not rewrite established live records, permitted earlier archive estimates reconcile idempotently, later dates do not overwrite earlier estimates, and unknown baseline records are not marked newly discovered by repeat live ingestion. Full suite passes.
