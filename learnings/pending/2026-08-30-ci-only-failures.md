# Learning Record

## Record Type

- **PATTERN** — a reusable, better way discovered during implementation.

---

## Metadata

- **Date Recorded:** 2026-08-30
- **Affected Subsystem:** CI/CD workflow (`docker/metadata-action` in `.github/workflows/release.yml`)
- **Related Files:** `.github/workflows/release.yml`
- **Related Spec:** `SPECS.md` (Release 1.0.0 — Seller Name, Docker, CI/CD, Ubuntu Deployment)

---

## Symptom / Context

After pushing the Release 1.0.0 commits to `main`, the GitHub Actions
`Release` workflow failed at the "Compute image tags" step with:

```
Error: Invalid value for enable attribute:
```

The local Docker image built and ran correctly end-to-end. All 41 pytest
tests passed locally. The workflow YAML was syntactically valid
(validated via `yaml.safe_load`). The failure was only visible on
GitHub's runner, not on the developer's Mac.

---

## Root Cause

`docker/metadata-action@v5` has a known bug
([docker/metadata-action#545](https://github.com/docker/metadata-action/issues/545))
where `setGlobalExp()` returns an **empty string** for the built-in
expressions `{{is_default_branch}}` and `{{is_tag}}` instead of
`"true"` / `"false"`. The action then rejects the empty value with
"Invalid value for enable attribute: ".

The bug is fixed on `v6` (and the maintainer opened PR #662 to improve
the error message on `v5` after the same issue was reported by
multiple users in August 2025).

The YAML was always valid; the bug is in the action's runtime template
evaluation, which only runs on GitHub's hosted runner and cannot be
exercised from a Mac.

---

## Prevention Rule

**When designing GitHub Actions workflows, pin the most recent major
version of any third-party action.** Avoid `@v5`-and-older on actions
that handle complex template expressions, because:

1. The runtime is hidden behind `actions/checkout` and only fully
   executes on GitHub's runner, not on the developer's machine.
2. There is no easy local validator that catches this class of bug
   (yamllint doesn't run the action, actionlint only checks the
   step's `with:` block, not the action's internal template engine).
3. v5+ releases of major actions like `docker/metadata-action`,
   `docker/build-push-action`, and `docker/login-action` are
   well-maintained and largely source-compatible with their previous
   major; the cost of bumping is small.

**Pre-flight check before pushing CI changes to a fresh workflow:**
for each `uses: third/action@<version>` line, check that the version
is the current `master` on the action's GitHub repo, and check the
action's `CHANGELOG.md` / release notes for any breaking changes
between major versions. This takes 30 seconds and catches the class
of "works locally, fails on the runner" bug.

**When the workflow fails on a fresh push:** treat the failure log as
ground truth and trace the failing step's input back to the action's
source code on `master` (not the published `v*`). The fix is often a
version bump, not a YAML change.

---

## Blueprint

```yaml
# BAD (v5 has #545):
- uses: docker/metadata-action@v5
  with:
    tags: |
      type=raw,value=latest,enable={{is_default_branch}}
      type=raw,value={{tag}},enable={{is_tag}}

# GOOD (v6 fixes #545, source-compatible):
- uses: docker/metadata-action@v6
  with:
    tags: |
      type=raw,value=latest,enable={{is_default_branch}}
      type=raw,value={{tag}},enable={{is_tag}}
```

Other actions in the same family with similar concerns as of 2026-08:
- `actions/checkout@v4` — fine, v4 is current.
- `actions/setup-python@v5` — fine.
- `docker/login-action@v3` — fine; v4 also exists.
- `docker/build-push-action@v5` — current, fine. v6 exists but is
  recently released; pin `@v5` for stability unless the spec needs
  v6-specific features.

---

## Verification

- Push the workflow fix; watch the Actions tab. Step 5 (Compute image
  tags) now succeeds and prints:
  `Generated tags: ghcr.io/fe4rlesscloak/laptop-tracker:sha-<short>,ghcr.io/fe4rlesscloak/laptop-tracker:latest`
- The subsequent "Build and push image" step succeeds, publishing
  `:latest` and `:sha-<short>` to ghcr.io.
- `uv run --extra dev pytest` continues to pass locally (workflow
  changes don't touch Python code).

---

## Evolution Candidates

### Candidate 1

- **Destination:** `SKILL`
- **Priority:** Medium
- **Status:** PENDING
- **Suggested Target:** new skill file `.agents/skills/github-actions.md` (does not yet exist)

#### Suggestion

Create a new domain skill `.agents/skills/github-actions.md` documenting
the runtime-validation gap (no easy way to test Actions YAML from a Mac;
`actionlint` and `yamllint` are partial checks only; the most
exhaustive validation is "push and read the runner log") and the
version-pinning policy (use the current major of each third-party
action; check `master` / `CHANGELOG.md` on the action's repo before
introducing a new action in a workflow).

Include a "Quick pre-flight checklist for new CI workflow files" with
the steps a future agent should run before committing a new
`.github/workflows/*.yml` file: (1) pin to current major, (2) run
`actionlint` if available, (3) read the action's `action.yml` for the
exact `inputs:` schema, (4) for actions that handle templates, verify
against the action's `__tests__/` to confirm the syntax works as
written.

#### Rationale

CI/CD is now a load-bearing part of this project (Release 1.0.0 ships
it). Future Evolution sessions will touch the workflow file again
(adding new tags, new actions, new triggers, new secrets). The
"works on my Mac, fails on the runner" class of failure is silent
until the first push, and the cost of catching it in pre-flight is
low. A small dedicated skill saves the next session from re-discovering
this the same way I did.

### Candidate 2

- **Destination:** `SPECS`
- **Priority:** High
- **Status:** PENDING
- **Suggested Target:** `SPECS.md` Release 1.0.0 spec, Unit 6 (CI/CD workflow) — Verification section

#### Suggestion

Update the Unit 9 verification list in the Release 1.0.0 spec to
include a "Workflow validation pre-flight" step. Currently the spec
says only that "the workflow YAML passes `actionlint` or `yamllint`
(no schema errors)" — but neither of these catches the action's
runtime template engine. Add a line: "For each `uses: third/action@<v>`
in the workflow, confirm the version is the action's current major by
checking the action's `master` branch; cite the check in the PR
description."

#### Rationale

The Release 1.0.0 spec is "active" until the implementation is fully
verified. If the spec is reused as a template for future release
specs (Release 1.1, Release 2.0, etc.), the verification list should
encode the lesson learned here. Without this update, a future
Evolution session will copy Unit 9 verbatim and repeat the same bug.
