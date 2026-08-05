
# AGENTS.md

## 1. Project Snapshot
* **Tech Stack:** Python 3.10+; `requests` + `beautifulsoup4` for scraping; `sqlite3` (stdlib) for storage; CSV/JSON export via stdlib
* **Build Command:** `uv sync`
* **Test Command:** `uv run --extra dev pytest`
* **Run Command:** `uv run python -m scraper`
* **Lint/Format Command:** `python -m flake8` (optional; not yet configured)

---

## 2. Instruction Priority

When instructions conflict, follow them in this order:

1. Direct user request
2. Active SPECS.md
3. AGENTS.md
4. Skill documents (meta-skills and domain skills)
5. Existing project conventions

### 2.1 Evolution Guardrails

The **Repository Evolution** skill may update `AGENTS.md`, skills, and templates to keep the instruction system effective. This authority is bounded: it must never remove or weaken **critical invariants** — security controls (e.g., 2FA, secrets handling), architectural constraints, or the ownership model defined in Section 5. When an evolution change touches a critical invariant, flag it for explicit developer approval rather than applying it silently.

## 3. Core Operating Directives

* **Interview First:** When facing ambiguous specs, missing context, or architectural trade-offs, interview the developer before writing code. Interview only when unanswered questions materially affect correctness, architecture, security, or user-visible behavior.
* **Don't Assume:** Verify assumptions using repo search tools, live logs, or direct inspection. Never invent API schemas, path structures, or external dependencies.
* **Define "Done" Observably:** A task is complete only when the required implementation is finished and verified by an observable signal appropriate to the change (for example, passing tests, successful builds, green terminal logs, or expected application behavior).
* **Surgical Edits:**  Modify only files directly required by the active spec, including shared dependencies, tests, configuration, and documentation. Do not refactor adjacent unprompted code or change code formatting styles outside your scope.
* **Implement by Logical Units:** Respect the logical reading order of `SPECS.md`, but implement shared foundational dependencies (data models, base utilities) before consuming feature UI—regardless of list position.
* **Detailed Git Commit Messages:** When commits are requested or running in autonomous mode, use structured commit messages. Write structured commit messages detailing *what* changed, *why* it changed, and *which spec item* was satisfied. Never issue generic commits (e.g., "fixed bug"). 
* **Point Docs at Live Code:** Reference exact file paths (`src/services/auth.ts`) rather than describing logic in prose. Keep markdown docs sparse and code-pointer heavy to eliminate doc drift.
* **Include Code Blueprints:** Every custom pattern or skill document must contain concrete, copy-pasteable inline code examples showing the target pattern.
* **Prevent Repeat Mistakes:** If an iteration fails because of agent behavior, route the root cause through `learnings/pending/` as an Evolution Candidate so the next Repository Evolution session can strengthen the relevant rule, skill, or spec before retrying. If the same class of mistake repeats, escalate it in `learnings/pending/` so future iterations cannot make the same error.

---

## 4. Skill Routing

Before performing work, load the corresponding skill document if it exists and follow its guidance unless it conflicts with higher-priority instructions.

### 4.1 Meta-Skills

Meta-skills govern the repository's instruction system itself. Load them based on the session type:

| Session type | Skill to load |
|---|---|
| Implementing the active spec | `.agents/skills/implementation/SKILL.md` |
| Evolving repository guidance / planning | `.agents/skills/repository-evolution/SKILL.md` |

### 4.2 Domain Skills

Domain skills encode reusable conventions for a specific technical area. They are defined under `.agents/skills/` as they are created. Load the relevant skill before modifying code in that domain.

The following are examples; the evolver can create any skill it deems necessary.

* **Frontend Development:** `.agents/skills/frontend.md` [Populate path when created]
* **Backend & API Routes:** `.agents/skills/backend.md` [Populate path when created]
* **Database & Migrations:** `.agents/skills/database.md` [Populate path when created]
* **Testing & Verification:** `.agents/skills/testing.md` [Populate path when created]
* **OLX Pakistan Scraping:** `.agents/skills/olx-scraping.md` — site HTML structure, URL scheme, pagination, price/time parsing

If a skill file is missing, continue using AGENTS.md alone and report the missing skill.

---

## 5. Operational Documents & Ownership

The repository's operational documents are owned and maintained by the **Repository Evolution** skill. Implementation sessions do not perform high-level documentation changes.

### 5.1 Document Ownership

| Document | Owner | Purpose |
|---|---|---|
| `SPECS.md` | Repository Evolution (content) / Implementation (check-off) | Active specification of work to implement |
| `BLOCKED.md` | Implementation (write / resolve) / Evolution (maintain) | The Handbrake: record blockers and halt |
| `TECH_DEBT.md` | Repository Evolution | Compromise tracker for intentional trade-offs |
| `learnings/pending/` | Implementation (write) / Evolution (evaluate) | New learning queue awaiting evaluation |
| `learnings/archive/` | Repository Evolution | Evaluated learning records (historical) |
| `REVIEWER_FINDINGS.md` | Repository Evolution (content) / Implementation (resolve) | Audit log of regressions and rule violations |
| `PROMPTS.md` | Repository Evolution | Reusable loop scripts and prompts |

### 5.2 Write Permissions

* **Implementation** may write to `BLOCKED.md`, `learnings/pending/`, and `.logs/` only. It may also **check off** (`[ ]` → `[x]`) completed items in `SPECS.md` — and nothing else in that file: no content edits, no reordering, no scope changes. It may **mark** `BLOCKED.md` blockers as `RESOLVED` (with a note on how) and **mark** `REVIEWER_FINDINGS.md` findings as `Resolved` (with a note on how) — status toggles and resolution notes only, no editing of the underlying problem/action content. It may propose guidance changes via Evolution Candidates in `learnings/pending/`, but must not edit `AGENTS.md`, skills, templates, `SPECS.md` content, `TECH_DEBT.md`, or `REVIEWER_FINDINGS.md` finding content.
* **Repository Evolution** owns and may update all operational documents and repository guidance. It drains `learnings/pending/`, promotes durable knowledge into guidance, and moves evaluated records to `learnings/archive/`.

### 5.3 Document Definitions

* **`BLOCKED.md` (The Handbrake):** If you hit an environment blocker, missing secret, or failing third-party endpoint, write the exact error and requirements to `BLOCKED.md` and halt immediately. Do not attempt speculative workarounds.
* **`TECH_DEBT.md` (Compromise Tracker):** Record only intentional temporary compromises that should be revisited. Do not record ordinary implementation decisions.
* **`learnings/pending/` (Learning Queue):** After resolving a non-obvious bug, repository quirk, or plan deviation, Implementation writes a single learning file here (see `LEARNINGS.template.md`). Each file carries one or more Evolution Candidates with a **Destination** (`SPECS` / `TECH_DEBT` / `PROMPTS` / `SKILL` / `AGENTS`) and **Priority**. The evolver reads only this directory — the directory listing is the list of new learnings, so token cost stays proportional to new findings, not the total archive.
* **`learnings/archive/` (Evaluated Records):** The evolver moves each evaluated learning here after promoting durable knowledge into guidance. Implementation does not read the archive; it reads the distilled guidance (skills / `AGENTS.md` / `TECH_DEBT.md`) that the evolver keeps current.
* **`REVIEWER_FINDINGS.md` (Audit Log):** On session startup, read `REVIEWER_FINDINGS.md`. Address any listed architectural regressions, rule violations, or unhandled edge cases flagged by background reviewer agents. If the file is absent, continue normally.
* **`PROMPTS.md` (Loop Scripts & Prompts):** Store reusable autonomous execution prompts, CLI invocation flags, and Ralph Loop bash scripts.

### 5.4 Template Instantiation

When creating any operational or instruction file for the first time (such as `SPECS.md`, `BLOCKED.md`, `TECH_DEBT.md`, a learning record in `learnings/pending/`, `REVIEWER_FINDINGS.md`, `PROMPTS.md`, or domain skill documents), instantiate it from the corresponding template in `.agents/templates/`. Preserve the template structure and headings, replacing placeholder values with project-specific content. If no template exists, report the missing template and do not invent a new format.


---

## 6. Execution Loop & Logging Standards

When running inside an autonomous execution loop:

* **Session Isolation:** Treat every loop run as a fresh environment. Read `AGENTS.md` and active `SPECS.md`, execute one spec item, run test suites, update docs, commit, and terminate.
* **Save Iteration Logs:** Pipe all terminal stdout/stderr for each run into `.logs/run-<timestamp>.log`. You may create the directory automatically.
* **Standard Exit Codes:**
  * `0_DONE` — All items in `SPECS.md` are completed, verified, and checked off.
  * `1_BLOCKED` — Execution halted; blocker details written to `BLOCKED.md`.
  * `2_BUDGET_EXCEEDED` — Token or context window limit reached; state committed for resumption.
  * `3_STUCK` — Tests repeatedly failing or loop making no git progress across iterations.

Implementation sessions map their completion to these exit codes; Repository Evolution sessions use them to decide whether to plan new work or revisit guidance.



## 7. Security

- Never commit secrets.
- Never invent credentials.
- Never disable security checks merely to satisfy tests




