---
name: implementation
description: Implement the active specification using the repository's operational guidance.
---

# Domain Skill: Implementation

## Purpose

Implement the active specification using the repository's operational guidance.

This skill is responsible for producing production-ready code, verification artifacts, and implementation feedback. It follows the repository's instruction system but does not evolve it directly.

The objective is to satisfy the active specification with the minimum necessary changes while preserving correctness, maintainability, and repository consistency.

---

## Lifecycle

Follow this ordered sequence every session. Do not skip steps.

1. Read `AGENTS.md` and the active `SPECS.md`.
2. Read `REVIEWER_FINDINGS.md` and address any `Pending` findings in scope.
3. Implement the spec in logical order of foundational dependencies first.
4. Verify each unit with an observable signal.
5. Check off completed items in `SPECS.md`.
6. Record discoveries or plan deviations as learning files in `learnings/pending/`.
7. Report the exit code (`0_DONE`, `1_BLOCKED`, `2_BUDGET_EXCEEDED`, `3_STUCK`).
8. Present the results and **wait for the developer's explicit yes/no**.
9. On **yes**, hand off back to the repository evolution skill (see Handoff to Repository Evolution).

---

## Repository Inputs

Review before modifying code:

- `AGENTS.md`
- Active `SPECS.md`
- Relevant domain skills
- `learnings/pending/`
- `REVIEWER_FINDINGS.md`

Inspect the repository before making assumptions.

---

## Implementation Principles

- Implement the active specification.
- Inspect before assuming.
- Modify only files required by the specification.
- Prefer existing repository patterns over introducing new ones.
- Preserve existing architecture and conventions.
- Keep changes focused and intentional.

---

## Documentation Responsibilities

Implementation may write to `BLOCKED.md`, `learnings/pending/`, and `.logs/` only. It may also **check off** (`[ ]` → `[x]`) completed items in `SPECS.md`, **mark** `BLOCKED.md` blockers as `RESOLVED`, and **mark** `REVIEWER_FINDINGS.md` findings as `Resolved` — status toggles and resolution notes only, never edits to underlying content. It must not perform high-level documentation changes — those belong to Repository Evolution.

### BLOCKED.md

Update when implementation cannot continue because of:

- missing credentials,
- unavailable services,
- missing dependencies,
- environment failures,
- unresolved external blockers.

Record the exact error and halt further implementation.

When a blocker is later resolved, mark its entry `RESOLVED` and add a note explaining how it was resolved.

---

### SPECS.md check-off

As each implementation unit is completed and verified, toggle its checkbox (`[ ]` → `[x]`) in `SPECS.md`. Do **not** edit spec content, reorder units, or change scope. Check-off is the only permitted write to `SPECS.md`.

---

### REVIEWER_FINDINGS.md

On session startup, read `REVIEWER_FINDINGS.md` and address any `Pending` findings in scope. When you resolve a finding, mark its status `Resolved` and add a note explaining how — do not edit the finding's problem, severity, or required-action content.

---

### learnings/pending/

Record repository discoveries made during implementation as a **single learning file** in `learnings/pending/` (see `LEARNINGS.template.md`). Choose a record type:

- **QUIRK** — non-obvious repository behavior,
- **DEVIATION** — you did something differently than planned due to constraints,
- **PATTERN** — a reusable, better way discovered during implementation.

When a discovery appears reusable across future work, attach one or more **Evolution Candidates**, each with a **Destination** (`SPECS` / `TECH_DEBT` / `PROMPTS` / `SKILL` / `AGENTS`) and **Priority**. For example, a deviation caused by a wrong spec should carry a candidate to `SPECS` (fix the spec) and, if it was a compromise, a candidate to `TECH_DEBT` (record the trade-off).

---

### Logs

Pipe terminal stdout/stderr into `.logs/run-<timestamp>.log` for each run.

---

## Escalation

When implementation discovers reusable repository knowledge:

1. Write a learning file in `learnings/pending/`.
2. Attach Evolution Candidates with Destination and Priority (see `LEARNINGS.template.md` for the required fields).
3. Continue implementation whenever possible.

Repository guidance is promoted during Repository Evolution, not during implementation. Implementation may only propose guidance changes via Evolution Candidates in `learnings/pending/`; it must not edit `AGENTS.md`, skills, templates, `SPECS.md` content, `TECH_DEBT.md`, or `REVIEWER_FINDINGS.md`.

---

## Verification

Before considering implementation complete:

- [ ] Active specification satisfied.
- [ ] Required verification completed.
- [ ] Completed `SPECS.md` items checked off (`[ ]` → `[x]`), with no content edits.
- [ ] Modified files are intentional.
- [ ] No unrelated files changed.
- [ ] Implementation findings documented where appropriate.
- [ ] No high-level documentation was modified (only `BLOCKED.md`, `learnings/pending/`, and `.logs/`).

Implementation sessions map their completion to the exit codes in `AGENTS.md` Section 6 (`0_DONE` when the spec item is complete and verified; `1_BLOCKED` when halted with a blocker recorded in `BLOCKED.md`).

---

## Handoff to Repository Evolution

Once implementation is complete and verified, hand the work back to the repository evolution skill so it can fold learnings into guidance and plan the next round.

### Interactive session

1. Present the results (what was implemented, verified, and recorded) to the developer and **wait for an explicit yes/no**.
2. If the developer requests changes, continue implementing and re-present.
3. Only on an explicit **yes**, load the repository evolution skill (`.agents/skills/repository-evolution/SKILL.md`) and hand off.

### Autonomous loop

In the loop, each run is isolated. End the implementation run with `0_DONE` once the spec item is complete and verified, then **wait for the developer's explicit yes/no** before the next run loads the repository evolution skill to drain `learnings/pending/` and plan the next round.

Do not hand off until the work is complete and approved — never proceed to the next phase without an explicit **yes**.
