# Learning Record

Record only non-obvious, repository-specific findings that future sessions are likely to repeat. Do not document ordinary bugs or feature implementations.

Each learning is a **single file** placed in `learnings/pending/` by Implementation. The Repository Evolution skill reads only `learnings/pending/`, evaluates each file, promotes durable knowledge into guidance, then moves the file to `learnings/archive/`.

---

## Record Type

Choose one:

- **QUIRK** — non-obvious repository behavior or edge case future sessions may repeat.
- **DEVIATION** — implementation did something differently than planned due to constraints.
- **PATTERN** — a reusable, better way discovered during implementation.

---

## Metadata

- **Date Recorded:** YYYY-MM-DD
- **Affected Subsystem:** `e.g., Prisma Migrations`
- **Related Files:** `src/db/...`
- **Related Spec:** `SPECS.md` (optional)

---

## Symptom / Context

Describe the observable failure or the situation that forced a deviation.

## Root Cause

Explain the underlying technical or planning reason.

## Prevention Rule

A concise rule future agents should follow.

## Blueprint

```typescript
// Minimal correct implementation
```

## Verification

How to confirm the fix works.

Examples:

- `pnpm test` passes
- Build succeeds
- API returns HTTP 200
- Migration completes successfully

---

## Evolution Candidates

Each learning may propose **one or more** changes to repository guidance. Each candidate has a **Destination** (where the change goes) and a **Priority** (how urgently the evolver must act). A single deviation may spawn multiple candidates (e.g., one to `SPECS` and one to `TECH_DEBT`).

**Status ownership:** Implementation always writes `Status: PENDING`. Only the **Repository Evolution** skill changes it to `ACCEPTED` or `REJECTED` when it evaluates the candidate.

### Candidate 1

- **Destination:** `SPECS` | `TECH_DEBT` | `PROMPTS` | `SKILL` | `AGENTS`
- **Priority:** Low | Medium | High
- **Status:** PENDING | ACCEPTED | REJECTED
- **Suggested Target:** `e.g., SPECS.md, frontend.md, PROMPTS.md`

#### Suggestion

Describe what repository instruction or document should be added or changed.

#### Rationale

Explain why this should become repository guidance rather than remain feature-specific.

### Candidate 2 (optional)

- **Destination:** ...
- **Priority:** ...
- **Status:** PENDING | ACCEPTED | REJECTED
- **Suggested Target:** ...

#### Suggestion

...

#### Rationale

...

---

## Destination Priority (for the Evolver)

The evolver processes candidates in this order of obligation:

1. **SPECS** — MUST reconcile. The literal specification changed during implementation; update it before planning new work or the next session repeats the mistake.
2. **TECH_DEBT** — SHOULD record. An intentional compromise was made; capture it for traceability and future revisit.
3. **PROMPTS** — SHOULD evaluate. Implementation proposes a reusable prompt/script; decide whether to accept it into `PROMPTS.md`.
4. **SKILL / AGENTS** — MAY consider. Discretionary; the evolver decides whether to promote the proposed guidance change.
