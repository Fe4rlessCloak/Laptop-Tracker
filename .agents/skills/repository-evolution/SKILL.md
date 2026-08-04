---
name: repository-evolution
description: Prepare the repository for implementation by planning, interviewing, and evolving repository guidance.
---

# Domain Skill: Repository Evolution

## Purpose

Prepare the repository for implementation.

This skill coordinates repository planning, interviews the developer when required, maintains the repository's operational documentation, and evolves repository guidance based on previous implementation sessions.

The objective is to ensure future implementation work becomes more predictable, reusable, and autonomous.

---

## Lifecycle

Follow this ordered sequence every session. Do not skip steps.

1. Review the current repository guidance (`AGENTS.md`, skills, templates).
2. Review `learnings/pending/` and `REVIEWER_FINDINGS.md`.
3. **Ask the developer for the interviewing verbosity level** (Extreme / Moderate / Low).
4. Interview the developer to resolve planning or architectural uncertainty, at the chosen verbosity.
5. Produce or update planning artifacts (`SPECS.md`).
6. Promote reusable knowledge into repository guidance; drain `learnings/pending/`.
7. Verify the repository's instruction system remains consistent.
8. Present `SPECS.md` and **wait for the developer's explicit yes/no**.
9. On **yes**, hand off to the implementation skill (see Handoff to Implementation).

---

## Repository Inputs

Review these documents before making planning decisions:

- `AGENTS.md`
- Active `SPECS.md`
- Domain skills
- `learnings/pending/` (the learning queue — read only this directory, not the archive)
- `REVIEWER_FINDINGS.md`

If a required operational document does not exist, create it using the corresponding template from `.agents/templates/`.

Never invent the structure of repository documents.

---

## Repository Outputs

Depending on the session, this skill may create or update:

- `AGENTS.md`
- `SPECS.md`
- Domain skills
- Repository templates
- `learnings/archive/` (move evaluated records here)
- `TECH_DEBT.md`
- `BLOCKED.md`
- `REVIEWER_FINDINGS.md`
- `PROMPTS.md`

Only modify documents whose evolution is justified by the current session.

---

## Interviewing

Interview the developer only when repository inspection cannot confidently resolve:

- architectural decisions,
- reusable repository conventions,
- planning uncertainty,
- instruction evolution.

Ask one question at a time.

Do not interview for feature-specific implementation details.

### Interviewing Verbosity

At the start of the interview phase, ask the developer to choose a verbosity level (default: **Moderate**). The choice governs how deeply you question and how much clarity you provide. The developer may change the level mid-interview.

- **Extreme** — Ask about every minute detail relevant to the decision. For each option or concept you present, explain what it means in plain terms (avoid unexplained jargon) and give clear **pros and cons / trade-offs** so the developer can choose informed. Best for beginners or those who want to understand the "why" behind each decision.
- **Moderate** — Ask about major high-level details plus some low-level implementation details. Assume reasonable technical familiarity; give brief pros/cons on consequential decisions but do not over-explain basic concepts.
- **Low** — Ask only when truly blocked or when a decision materially affects correctness, architecture, or security. Make reasonable assumptions and proceed. No concept explanation; assume expert familiarity.

Verbosity governs depth and clarity only — it does not change the "ask one question at a time" rule.

---

## Knowledge Promotion

Treat `learnings/pending/` as the repository evolution backlog. The directory listing is the list of new learnings — read only the files in `pending/`, never the whole archive. This keeps token cost proportional to new findings.

Each pending learning should be evaluated to determine whether it should:

- remain a historical learning,
- become repository guidance,
- expand an existing domain skill,
- create a new domain skill,
- update a repository template,
- be recorded in `TECH_DEBT.md`,
- or be rejected as feature-specific.

Promote only reusable repository knowledge. After evaluation, move each learning file from `learnings/pending/` to `learnings/archive/`.

### Evolution Candidates

An **Evolution Candidate** is a proposal written by an Implementation session into a learning file in `learnings/pending/`, requesting that the next Repository Evolution session change repository guidance or a document. It is the only channel through which Implementation may propose guidance changes.

Each candidate must be evaluated against the following fields (see `LEARNINGS.template.md`):

- **Destination:** `SPECS` | `TECH_DEBT` | `PROMPTS` | `SKILL` | `AGENTS`
- **Priority:** Low | Medium | High
- **Status:** `PENDING` | `ACCEPTED` | `REJECTED`
- **Suggested Target:** which document or skill it proposes to change
- **Suggestion:** the concrete instruction change proposed
- **Rationale:** why it should become repository guidance rather than remain feature-specific

Process candidates in order of obligation:

1. **SPECS** — MUST reconcile. The literal specification changed during implementation; update it before planning new work, or the next session repeats the mistake.
2. **TECH_DEBT** — SHOULD record. An intentional compromise was made; capture it for traceability and future revisit.
3. **PROMPTS** — SHOULD evaluate. Decide whether to accept the proposed prompt/script into `PROMPTS.md`.
4. **SKILL / AGENTS** — MAY consider. Discretionary; decide whether to promote the proposed guidance change.

When evaluating a candidate:

1. Confirm it is reusable repository knowledge, not feature-specific detail.
2. Check it does not weaken a **critical invariant** (see Guardrails below).
3. Decide to accept, reject, or defer it.
4. Update the candidate's `Status` to record the outcome.

---

## Guardrails

Repository Evolution may update `AGENTS.md`, skills, and templates to keep the instruction system effective. This authority is bounded: it must never remove or weaken **critical invariants**:

- security controls (e.g., 2FA, secrets handling),
- architectural constraints,
- the ownership model defined in `AGENTS.md` §5.

When an evolution change touches a critical invariant, flag it for explicit developer approval rather than applying it silently.

---

## Planning

When implementation is requested:

- reuse an existing active specification when appropriate;
- otherwise create one using the repository template;
- identify dependencies;
- define observable verification;
- describe what must be implemented rather than how.

---

## Principles

- Prefer repository inspection over assumptions.
- Prefer interviews over guessing.
- Prefer evolving existing documentation over creating new documents.
- Prefer reusable repository guidance over feature-specific documentation.
- Keep repository instructions concise, consistent, and implementation-agnostic.

---

## Verification

Before concluding a Repository Evolution session:

- [ ] Repository guidance has been reviewed.
- [ ] `learnings/pending/` has been drained — every learning evaluated and moved to `learnings/archive/`.
- [ ] Evolution Candidates have been resolved (accepted, rejected, or deferred) in priority order, with SPECS candidates reconciled first.
- [ ] No critical invariant was weakened without explicit developer approval.
- [ ] Planning artifacts are ready for implementation.
- [ ] Repository instructions remain consistent.
- [ ] New reusable knowledge has been captured where appropriate.

Repository Evolution sessions map their completion to the exit codes in `AGENTS.md` Section 6 (`0_DONE` when planning is complete and guidance is consistent).

---

## Handoff to Implementation

Once planning is complete and verified, hand the work off to the implementation skill. The active `SPECS.md` is the single handoff artifact — record all planning decisions and constraints inside the spec so the implementer needs nothing else.

### Interactive session

1. Present the finished `SPECS.md` to the developer and **wait for an explicit yes/no**.
2. If the developer requests changes, revise the spec and re-present it.
3. Only on an explicit **yes**, load the implementation skill (`.agents/skills/implementation/SKILL.md`) and begin executing the active spec in the same session.

### Autonomous loop

In the loop, each run is isolated. End the evolution run with `0_DONE` once planning is complete and verified, then **wait for the developer's explicit yes/no** before the next run loads the implementation skill and executes the active `SPECS.md`. Use the reusable handoff prompt in `PROMPTS.md` to drive the transition.

Do not hand off until the spec is complete and approved — an incomplete spec (unresolved questions, missing verification) is a failed interview, not a handoff. In both paths, never proceed to implementation without an explicit **yes**.
