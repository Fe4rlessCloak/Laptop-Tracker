# Learning Record

Record only non-obvious, repository-specific findings that future sessions are likely to repeat. Do not document ordinary bugs or feature implementations.

Each learning is a **single file** placed in `learnings/pending/` by Implementation. The Repository Evolution skill reads only `learnings/pending/`, evaluates each file, promotes durable knowledge into guidance, then moves the file to `learnings/archive/`.

---

## Record Type

Choose one:

- **DEVIATION** — implementation did something differently than planned due to constraints.

---

## Metadata

- **Date Recorded:** 2026-10-04
- **Affected Subsystem:** Monitoring storage (`scraper/monitoring.py`)
- **Related Files:** [`scraper/monitoring.py`](scraper/monitoring.py), [`scraper/config.py`](scraper/config.py), [`tests/test_monitoring.py`](tests/test_monitoring.py)
- **Related Spec:** [`SPECS.md`](SPECS.md) — "Persistent Monitoring and Predefined Listing Reports"

---

## Symptom / Context

Unit 1 (durable monitoring model + historical import) was implemented while the active
specification's Dependencies section still lists two unchecked prerequisites
([`SPECS.md`](SPECS.md:389) and [`SPECS.md`](SPECS.md:390) ):

1. "Verify selected Grafana, Prometheus, SQLite plugin, and Python instrumentation
   versions and mini-PC architecture compatibility; lock dependencies and plugin
   security behavior before implementation consumers."
2. Operator-supplied runtime inputs (bind addresses, Grafana credentials, volume
   permissions) "during deployment".

The wording "before implementation consumers" does not name which units are
"consumers", so it is ambiguous whether the foundation-only Unit 1 is gated by (1).
Unit 1 consumes none of Grafana, Prometheus, or the SQLite datasource plugin, and (2)
is explicitly a deployment-time input. The work proceeded on Unit 1 only, leaving
Units 2–4 (which do consume those versions and runtime inputs) unstarted.

Separately, the reporting requirement "use `Asia/Karachi` for dashboard calendar
dates" cannot assume the IANA tz database is present. The runtime image is
`python:3.11-slim`, which does not ship `tzdata`; a bare `ZoneInfo("Asia/Karachi")`
raises `ZoneInfoNotFoundError` there even though it succeeds on the developer's macOS
host. Tests would pass locally while the container degraded at runtime.

## Root Cause

The specification was authored to gate *consumers* of the monitoring stack, but the
prerequisite text is unit-agnostic, so a session can reasonably wonder whether any
implementation may begin. Encoding the gate per-unit (or stating "Uni 1 is ungated")
would remove the ambiguity.

For the timezone, `zoneinfo` reads the tz database from the OS; slim container images
omit it. Relying on the host's tz data is not reproducible across environments.

## Prevention Rule

- Treat [`SPECS.md`](SPECS.md) prerequisites that name specific third-party
  technologies as gating only the units that actually consume those technologies;
  foundational storage/model units that do not consume them may proceed.
- Never depend on the host tz database for reporting dates. Resolve
  `Asia/Karachi` through `zoneinfo` when available and fall back to a fixed
  `UTC+05:00` offset (Pakistan has observed no DST since 2009) so slim images
  compute correct calendar dates without an extra dependency.

## Blueprint

```python
from datetime import datetime, timedelta, timezone

# Prefer the IANA zone when the tz database is present; otherwise use the fixed
# Pakistan Standard Time offset (no DST since 2009) so slim containers still
# bucket observations under the correct local calendar day.
try:
    from zoneinfo import ZoneInfo

    KARACHI_TZ = ZoneInfo("Asia/Karachi")
except (ImportError, KeyError):  # ZoneInfoNotFoundError subclasses KeyError
    KARACHI_TZ = timezone(timedelta(hours=5), name="PKT")


def to_karachi_date(timestamp_iso: str) -> str:
    parsed = datetime.fromisoformat(timestamp_iso)
    return parsed.astimezone(KARACHI_TZ).date().isoformat()
```

## Verification

- `uv run --extra dev pytest` → 68 passed (includes 27 new synthetic monitoring tests).
- `uv run python -m scraper.monitoring stats` prints discovery/observation totals.
- `uv run python -m scraper.monitoring import <path>` is idempotent on re-run.

---

## Evolution Candidates

**Status ownership:** Implementation always writes `Status: PENDING`. Only the **Repository Evolution** skill changes it to `ACCEPTED` or `REJECTED` when it evaluates the candidate.

### Candidate 1

- **Destination:** `SPECS`
- **Priority:** Medium
- **Status:** ACCEPTED
- **Suggested Target:** `SPECS.md` (monitoring specification, Dependencies section)

#### Suggestion

Clarify that the version-locking prerequisite gates only the units that consume the
monitoring stack (Units 2–4), and state explicitly that the foundational Unit 1
(monitoring storage + historical import) is ungated.

#### Rationale

The current ambiguity blocks or delays foundational work unnecessarily and will be
re-encountered by the next session that reaches Unit 1. Making the gate unit-scoped
keeps the specification actionable without weakening the version-locking requirement
where it actually matters.

### Candidate 2

- **Destination:** `TECH_DEBT`
- **Priority:** Medium
- **Status:** ACCEPTED
- **Suggested Target:** `TECH_DEBT.md`

#### Suggestion

Record the intentional compromise that reporting calendar dates resolve
`Asia/Karachi` via a fixed `UTC+05:00` fallback when the tz database is unavailable,
rather than adding a `tzdata` dependency. Revisit if Pakistan reintroduces DST or if
a future release pins a base image that already ships tz data.

#### Rationale

This is a deliberate trade-off (avoid a new locked dependency) with a real, narrow
failure mode (incorrect local dates if DST returns). TECH_DEBT is the intended
tracker for exactly this class of compromise.

### Candidate 3

- **Destination:** `SKILL`
- **Priority:** Medium
- **Status:** ACCEPTED
- **Suggested Target:** `.agents/skills/monitoring.md` (new domain skill)

#### Suggestion

Add a monitoring domain skill documenting: the two-database boundary (listing DB vs
monitoring DB), the discovery/observation/run distinction, the `(item_id, timestamp)`
observation idempotency key used by archive imports, the Asia/Karachi date
convention, and the operator-only `python -m scraper.monitoring import` action. Point
Units 2–4 sessions at [`scraper/monitoring.py`](scraper/monitoring.py) as the
authoritative model.

#### Rationale

Units 2–4 (instrumentation/exporter, snapshot publication/dashboards, deployment)
must extend this model without re-deriving its semantics or accidentally writing
listing/monitoring data into the wrong database. A domain skill keeps that contract
in one place instead of repeating it across specifications.

## Evolution Evaluation — 2026-10-04

- Candidate 1: Accepted with explicit developer approval. [SPECS.md](../../SPECS.md) now scopes external-tool checks to the work that uses them and runtime operator inputs to deployment verification. No required security/version check was removed.
- Candidate 2: Accepted with explicit developer approval; [DEBT-002](../../TECH_DEBT.md) records the existing fixed-offset compromise, older daylight-saving-date limits, and revisit triggers. The learning's claim about all slim images omitting timezone data was not promoted as a universal fact; actual image availability must be verified.
- Candidate 3: Accepted into [.agents/skills/monitoring.md](../../.agents/skills/monitoring.md), registered in [AGENTS.md](../../AGENTS.md). Guidance preserves the spec contract rather than blessing all existing helper behavior.
- Verification: 68 synthetic tests passed in this Evolution session. Inspection also identified two contract gaps recorded in [REVIEWER_FINDINGS.md](../../REVIEWER_FINDINGS.md); Unit 1 was reopened with corrective tests required. Application code was not changed during Evolution.
