# Active Environment Blockers

Document only blockers that prevent further progress. Remove or mark entries as `RESOLVED` once addressed.

---

## [BLOCKER-001] – Short Title

- **Date Halted:** YYYY-MM-DD HH:MM UTC
- **Status:** ACTIVE | RESOLVED
- **Active Spec:** `SPECS.md` (or path)
- **Affected Task:** Unit X – Description

### Summary

Brief explanation of why work cannot continue.

### Observable Error

```text
Paste the exact terminal output, stack trace, HTTP response, or error message.
```

### Root Cause

Known root cause, or write **Unknown** if not yet determined.

### Required Action

Describe exactly what a developer or operator must do to unblock the work.

Examples:

- Add missing API key `STRIPE_SECRET_KEY`
- Run `pnpm prisma migrate deploy`
- Grant access to staging database
- Fix third-party outage

### Verification

Describe how to confirm the blocker has been resolved.

Examples:

- `pnpm test` passes
- `GET /health` returns HTTP 200
- Authentication succeeds
- Build completes successfully

### Resolution

Leave blank until resolved.

- **Resolved By:**
- **Resolved On:**
- **Notes:**