# Reusable Loop Scripts & Prompts

Store reusable autonomous execution prompts, CLI invocation flags, and Ralph Loop bash scripts. Do not record one-off commands or feature-specific instructions.

**Write path:** The **Repository Evolution** skill writes entries to this file. **Implementation** does not write here directly — it proposes a reusable prompt/script via a learning file in `learnings/pending/` with an Evolution Candidate whose `Destination: PROMPTS`. The evolver decides whether to accept it.

---

## [PROMPT-001] – Handoff to Implementation

- **Date Recorded:** 2026-08-03
- **Purpose:** Drive the transition from a completed Repository Evolution (planning) session to an Implementation session.
- **Used By:** Repository Evolution

### Prompt

```
Planning is complete. Present the active SPECS.md and wait for the developer's explicit yes/no.

- On "no" or requested changes: revise the spec and re-present it.
- On "yes": hand off to the implementation skill.

1. Load the implementation skill (`.agents/skills/implementation/SKILL.md`).
2. Read the active `SPECS.md` — it is the single source of truth for what to build.
3. Execute the spec in logical order of foundational dependencies first.
4. Check off each completed item in `SPECS.md` as it is verified.
5. Record any discoveries or plan deviations as learning files in `learnings/pending/`.
6. Report the exit code: 0_DONE, 1_BLOCKED, 2_BUDGET_EXCEEDED, or 3_STUCK.
```

### CLI Invocation

```bash
# Interactive: switch to the implementation skill and begin executing the active spec.
# Autonomous loop: start a fresh implementation run that reads AGENTS.md and the active SPECS.md.
```

### Ralph Loop Script

```bash
#!/usr/bin/env bash
# Reusable autonomous loop script
# 1. Run a Repository Evolution session to plan and produce SPECS.md (exit 0_DONE).
# 2. Run an Implementation session to execute the active SPECS.md (exit 0_DONE).
# 3. Repeat: evolution -> implementation -> evolution -> ...
```

### Notes

Use this prompt at the end of a Repository Evolution session once planning is verified. In both the interactive session and the autonomous loop, wait for the developer's explicit **yes** before the implementation skill loads and executes the active `SPECS.md`. In the loop, the handoff is a separate run: the evolution run ends with `0_DONE` after approval, then a fresh implementation run loads the implementation skill.
