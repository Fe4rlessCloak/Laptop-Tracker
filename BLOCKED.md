# Active Environment Blockers

Document only blockers that prevent further progress. Remove or mark entries as `RESOLVED` once addressed.

---

## [BLOCKER-001] – GitHub issue intake unavailable during monitoring planning

- **Date Halted:** 2026-10-04 12:10 UTC
- **Status:** RESOLVED
- **Active Spec:** [SPECS.md](SPECS.md) (monitoring specification not yet drafted)
- **Affected Task:** Repository Evolution lifecycle step 3 – GitHub Issue intake

### Summary

Monitoring planning paused before the interview because open GitHub Issues could not be inspected through the attempted tools. No application code or monitoring specification has been changed. Pending learnings remain unevaluated.

### Observable Error

```text
--- GitHub open issues ---
GitHub CLI unavailable

Error: browserType.launchPersistentContext: Chromium distribution 'chrome' is not found at /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
Run "npx playwright install chrome"
```

### Root Cause

The GitHub CLI is not available on the terminal command path. The configured browser tool requires a Chrome installation that is absent at its expected location.

### Required Action

Provide a working GitHub issue-intake capability: install the GitHub CLI with repository access, restore the configured browser's Chrome installation, or enable an existing GitHub integration. Do not introduce application API clients or commit credentials for this process.

### Verification

An available tool successfully retrieves the repository's open GitHub Issues, including titles, bodies, and labels where issues exist, or confirms that no open issues exist. Resume the Evolution lifecycle at issue intake, then ask for interview verbosity before resolving monitoring architecture decisions.

### Resolution

- **Resolved By:** Repository Evolution session
- **Resolved On:** 2026-10-04 12:16 UTC
- **Notes:** The existing GitHub integration successfully listed open issues for Fe4rlessCloak/Laptop-Tracker and returned an empty list. Issue intake is complete; no CLI or browser installation is required for planning.

---

## [BLOCKER-002] – Local Docker daemon (OrbStack) not running for image build and container verification

- **Date Halted:** 2026-11-17 12:26 UTC
- **Status:** RESOLVED
- **Active Spec:** [SPECS.md](SPECS.md) — Units 4–5 (image verification & synthetic container integration)
- **Affected Task:** `docker build -t laptop-tracker:dev .` and synthetic multi-run container verification in Unit 5

### Summary

Units 2–3 and the Compose/documentation edits for Unit 4 are implemented and verified with `pytest` and `docker compose config`. Building `laptop-tracker:dev` and verifying `python -m scraper.web` inside a live container cannot proceed because the local Docker daemon (OrbStack) is stopped.

### Observable Error

```text
ERROR: failed to connect to the docker API at unix:///Users/abdullah/.orbstack/run/docker.sock; check if the path is correct and if the daemon is running: dial unix /Users/abdullah/.orbstack/run/docker.sock: connect: no such file or directory
```

### Root Cause

OrbStack / Docker Engine is not currently running on the developer's Mac.

### Required Action

Start OrbStack (Docker daemon) locally, then run `docker build -t laptop-tracker:dev .` and execute the synthetic container verification (and operator mini-PC checks once deployed).

### Verification

- `docker build -t laptop-tracker:dev .` exits `0`.
- `python -m scraper.web` serves `/health` and read-only SQLite endpoints inside the container sharing `laptop-tracker-data` with one-shot scraper runs.

### Resolution

- **Resolved By:** Implementation session (after user started OrbStack)
- **Resolved On:** 2026-11-17 12:31 UTC
- **Notes:** `docker build -t laptop-tracker:dev .` succeeded, both entrypoints (`python -m scraper --help` and `python -m scraper.web --help`) passed, and synthetic multi-run + container-recreation verification passed against an isolated Docker volume.
