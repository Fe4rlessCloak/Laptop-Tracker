# Komplex-Code — Template Harness

A **template harness** for running a coding assistant in a steady, repeatable, **user-in-the-loop** way. This repository is not an application. It is a set of instructions, skills, and templates that shape how work gets planned, carried out, and improved over time.

`AGENTS.md` here is a **draft** — you adapt it to your project (tech stack, build/test commands) before use.

## What this is

When you hand a coding assistant a project, it can drift: it invents details, edits files it should not touch, or repeats the same mistake. This harness prevents that by writing down, in one place, how the assistant should behave — and by keeping two jobs separate:

1. **Do the work.** Implement what the plan asks for, verify it, and stop.
2. **Improve the rules.** Between work sessions, look at what went wrong and make the rules better.

The person doing the work should not also be the person rewriting the rules, or the rules never get a chance to settle. That is why there are **two skills** that hand off to each other, with a human approving every transition.

## How it is organised

```
AGENTS.md                     The master set of rules (a draft — adapt to your project)
.agents/skills/
  implementation/SKILL.md     The "do the work" skill
  repository-evolution/SKILL.md  The "improve the rules" skill
.agents/templates/            Blank copies of the working documents
learnings/
  pending/                    New learnings awaiting evaluation (the queue)
  archive/                    Evaluated learnings (historical)
```

### The two skills

- [`.agents/skills/repository-evolution/SKILL.md`](.agents/skills/repository-evolution/SKILL.md) — the **evolver**. Plans, interviews you, produces `SPECS.md`, and evolves the rules. It asks for your **interviewing verbosity level** (Extreme / Moderate / Low) before interviewing.
- [`.agents/skills/implementation/SKILL.md`](.agents/skills/implementation/SKILL.md) — the **implementer**. Executes the active `SPECS.md`, verifies each unit, checks off items, and records learnings. It is deliberately not allowed to rewrite the rules.

### The working documents

Created as needed from templates in `.agents/templates/`:

- **`SPECS.md`** — the active plan of what to build. Implementation checks off completed items as it goes.
- **`BLOCKED.md`** — a record of anything that stopped work, and why.
- **`learnings/pending/`** — new discoveries and plan deviations, each in its own file, awaiting evaluation.
- **`learnings/archive/`** — evaluated learning records, moved here once processed.
- **`TECH_DEBT.md`** — intentional shortcuts that should be revisited later.
- **`REVIEWER_FINDINGS.md`** — an audit log of regressions and rule violations.
- **`PROMPTS.md`** — reusable prompts and scripts for running sessions.

## The working process (user-in-the-loop)

This is **not** a fully autonomous system. Every handoff between the two skills pauses for your explicit **yes/no**.

1. **Start with the evolver.** Prompt the AI (with the evolver skill loaded) with what you want to build, and specify your **interviewing verbosity level** (Extreme / Moderate / Low).
2. **The evolver interviews you**, then produces the planning artifacts — `SPECS.md` (and adapts `AGENTS.md` as needed).
3. **User-approved handoff.** The evolver presents `SPECS.md` and waits for your explicit **yes**. On yes, it hands off to the implementation skill.
4. **The implementer takes over.** It first reads `REVIEWER_FINDINGS.md` and addresses any pending findings, then reads the active `SPECS.md` and completes it — verifying each unit, checking off items, and recording anything it learned or did differently.
5. **Learnings communicate back.** The implementer writes learning files to `learnings/pending/` (with Evolution Candidates) so the evolver knows what to fold into guidance next round.
6. **User-approved handoff back.** The implementer presents its results and waits for your explicit **yes**. On yes, it hands off back to the evolver.
7. **The loop repeats.** The evolver drains `learnings/pending/`, promotes durable knowledge into guidance, and plans the next round.

```
evolver ──(plan, verbosity, approve SPECS)──▶ implementation ──(implement, verify, approve)──▶ evolver ──▶ ...
```

Both skills require **read/write access** to the repository — the evolver to plan and evolve guidance, the implementer to build and record learnings.

## Token efficiency: learnings are a queue, not an archive

Learnings are **not** one ever-growing file that every session must read. Instead:

- New learnings land in `learnings/pending/` as **individual files**.
- The evolver reads **only** `learnings/pending/` — the directory listing *is* the list of what's new, so token cost stays proportional to new findings, not the total history.
- After evaluation, the evolver moves each learning to `learnings/archive/`.
- Implementation does **not** read the archive; it reads the distilled guidance (skills / `AGENTS.md` / `TECH_DEBT.md`) that the evolver keeps current.

## Getting started

1. Copy this harness into your project.
2. Fill in the project details at the top of [`AGENTS.md`](AGENTS.md) (tech stack, build command, test command).
3. Start an evolver session: tell it what you want to build and set your interviewing verbosity.
4. Approve the produced `SPECS.md` to hand off to implementation.
5. Approve the implementation results to hand back to the evolver, and repeat.

## Notes

- This is a starting point, not a finished product. Expect to adjust the rules as you use them.
- The domain skill files (frontend, backend, database, testing) are **examples only** — the evolver can create any skill it deems necessary.
