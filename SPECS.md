# Spec: OLX Pakistan Laptop Scraper (MVP)

## 1. Objective & Scope
* **Goal:** Build a Python CLI scraper that fetches laptop listings from OLX Pakistan for the Islamabad and Rawalpindi areas, limited to a configurable recent time window (default 12–24 hours), stores them in a local SQLite database, and exports to CSV/JSON. This is a proof-of-concept to confirm we can reliably capture fresh listings.
* **Target Files/Directories:** `scraper/` (Python package), `data/` (SQLite DB + exports), `tests/`
* **Out of Scope (deferred to later specs):**
  - Deploying to the user's Ubuntu mini PC
  - Automated scheduling (cron/systemd) for daily/twice-daily runs
  - The "flag lucrative deals" analysis system (no ML)
  - Downloading listing images (we capture image URLs as text only)

## 2. Dependencies & Prerequisites
- [x] Python 3.10+ available on the machine
- [x] `requests` and `beautifulsoup4` installed (via `requirements.txt` / virtualenv)
- [x] Network access to `https://www.olx.com.pk/`

## 3. Implementation Units (Execution Order)
*Implement in logical order of foundational dependencies first, regardless of list position.*

- [x] **Unit 1: Project scaffolding & config**
  - [x] Create `scraper/` package, `requirements.txt`, and a `config.py` holding defaults (cities, time window, rate-limit delay, base URLs)
  - [x] Add `pyproject.toml` or `setup.cfg` so the package is runnable as `python -m scraper`
- [x] **Unit 2: Data model & storage layer**
  - [x] Implement `scraper/storage.py` — SQLite schema for listings (unique OLX item ID, title, price, price_numeric, currency, location, city, posted_at, relative_time, description, image_urls, item_url, is_featured, scraped_at)
  - [x] Implement upsert logic (insert new / update existing by item ID) and CSV/JSON export functions
  - [x] Add unit tests in `tests/test_storage.py`
- [x] **Unit 3: HTTP client & polite fetching**
  - [x] Implement `scraper/fetcher.py` — `requests`-based fetcher with a realistic browser User-Agent, configurable delay between requests, and retry/backoff on transient failures
  - [x] Add unit tests in `tests/test_fetcher.py` (mocked responses)
- [x] **Unit 4: Search-results parser**
  - [x] Implement `scraper/parsers.py` — parse listing cards from search-result HTML (title, price, location, relative time, item URL, thumbnail URL, Featured flag)
  - [x] Implement price normalization (e.g., `Rs 39,000` → 39000; `Rs 1.40 Lac` → 140000; `Rs 10.40 Lacs` → 1040000)
  - [x] Implement relative-time parsing (`N hours ago`, `N days ago`, `N weeks ago`) into an approximate age for the time-window filter
  - [x] Add unit tests in `tests/test_parsers.py` using captured HTML fixtures
- [x] **Unit 5: Item-detail parser**
  - [x] Implement parsing of an individual item page for the full description and image URLs (text only, no image download)
  - [x] Add unit tests in `tests/test_parsers.py`
- [x] **Unit 6: Orchestrator & CLI**
  - [x] Implement `scraper/cli.py` — CLI entry point with flags: `--cities` (default Islamabad, Rawalpindi), `--hours` (default 24), `--export` (csv/json/both), `--db` (path)
  - [x] Implement `scraper/runner.py` — orchestrates: fetch search pages per city → filter by time window → fetch item pages for descriptions → upsert to SQLite → export
  - [x] Add an integration test in `tests/test_runner.py` (mocked HTTP) verifying end-to-end flow

## 4. Verification Criteria
*Task is complete only when verified by an observable signal.*

* **Build Command:** `pip install -r requirements.txt`
* **Test Command:** `python -m pytest`
* **Expected Observable Behavior:**
  - `python -m scraper --cities islamabad rawalpindi --hours 24` completes and prints a summary (e.g., "Fetched N listings, M new, K updated")
  - A populated SQLite DB exists at `data/olx.db` with listing rows
  - CSV and/or JSON exports are written to `data/`
  - Running the command a second time upserts (no duplicate rows for the same item ID)
  - All unit/integration tests pass

## 5. Compatibility
- Preserve existing public APIs unless specified.
- Preserve backward compatibility unless explicitly waived.
- The scraper must remain polite to OLX: configurable delay between requests, no aggressive parallelism, no image downloads.

---

# Spec: OLX Pagination & Fresh-Listing Capture (Evolution)

## 1. Objective & Scope
* **Goal:** Extend the OLX laptop scraper to page through all search-result pages per city so it captures every listing within the configured recent time window (default 12–24h), instead of only the first page (~50 ads). OLX pushes older ads to the top even when sorted by newest, so the existing time-window filter (which reads each card's posted time from the search page, without visiting item links) is the primary gate that keeps the database clean of stale ads. Duplicate prevention is already handled by the `item_id` PRIMARY KEY + upsert. Note: an early-stop-on-duplicate optimization was considered but **removed** — featured ads break OLX's newest-first ordering, so the runner stops only on time-window exhaustion or the `MAX_PAGES` cap.
* **Target Files/Directories:** `scraper/runner.py`, `scraper/storage.py`, `scraper/config.py`, `scraper/cli.py`, `tests/test_runner.py`, `tests/test_storage.py`
* **Out of Scope:**
  - Filtering by the "Featured" badge — confirmed NOT needed. The time-window filter already drops old ads pushed to the top; any ad within the window is kept regardless of featured status.
  - Headless browser / infinite-scroll simulation — OLX exposes `?page=N`, so plain-HTTP pagination suffices.
  - Changing the storage schema or upsert semantics — duplicate prevention already works.

## 2. Dependencies & Prerequisites
- [x] Existing MVP scraper (all prior units complete and checked off)
- [x] Confirmed OLX supports `?page=N` pagination for the laptops category (developer-verified)
- [x] Real-world depth data: Rawalpindi 24h ads ≈ 5 pages; Islamabad 24h ads ≈ 11 pages

## 3. Implementation Units (Execution Order)
*Implement in logical order of foundational dependencies first, regardless of list position.*

- [x] **Unit 1: Storage helper for duplicate detection**
  - [x] Add `listing_exists(conn, item_id) -> bool` to `scraper/storage.py` (a simple `SELECT 1 FROM listings WHERE item_id = ?` wrapper). Note: this helper was originally added to support a duplicate early-stop that was later **removed**; it remains available for other callers but is not used to stop pagination.
  - [x] Add unit test in `tests/test_storage.py` verifying it returns True for a stored ID and False for an unknown one

- [x] **Unit 2: Pagination-aware search URL**
  - [x] Update `build_search_url` in `scraper/runner.py` (or add a helper) to accept a page number and append `?page=N` to the existing search URL
  - [x] Append `sorting=desc-creation` to the search URL so OLX returns newest-first ordering (without it, the default sort surfaces only old featured/relevance ads and the scraper captures nothing within the window)
  - [x] Add `MAX_PAGES = 20` to `scraper/config.py` as a safety cap against runaway loops

- [x] **Unit 3: Pagination loop in the runner**
  - [x] Refactor the per-city loop in `scraper/runner.py` to iterate pages 1..MAX_PAGES, stopping when a page contains no listings within the time window (time-window exhaustion) or when `MAX_PAGES` is reached
  - [x] Do **NOT** early-stop on a duplicate listing — featured ads break OLX's newest-first ordering, so a duplicate on an early page does not guarantee newer ads are absent from later pages
  - [x] Keep the existing behavior: within-window listings get their item page fetched for description/image enrichment, then upserted (repeat runs update already-stored listings)
  - [x] Add/update integration tests in `tests/test_runner.py` (mocked HTTP) covering: multi-page capture, no early-stop on duplicate, and early-stop on time-window exhaustion

- [x] **Unit 4: CLI (optional surface)**
  - [x] Confirm no new CLI flag is needed (there is no duplicate early-stop to toggle, so no `--no-early-stop`). Update `scraper/cli.py` help text only if the summary wording changes.

## 4. Verification Criteria
*Task is complete only when verified by an observable signal.*

* **Build Command:** `uv sync`
* **Test Command:** `uv run --extra dev pytest`
* **Expected Observable Behavior:**
  - `uv run python -m scraper --cities islamabad rawalpindi --hours 24` pages through multiple search pages per city and prints a summary
  - On a first run (empty DB), all listings within the window are captured across pages
  - On a repeat run, the runner does not early-stop on a duplicate; it re-fetches and updates already-stored listings (upsert), and no duplicate rows are created
  - Old ads pushed to the top (e.g., 7 days old) are dropped by the time-window filter without visiting their item pages
  - All unit/integration tests pass

## 5. Compatibility
- Preserve existing public APIs unless specified.
- Preserve backward compatibility unless explicitly waived.
- The scraper must remain polite to OLX: configurable delay between requests, no aggressive parallelism, no image downloads.

---

# Spec: GitHub Issue Intake for the Public Evolution Bot (Evolution)

## 1. Objective & Scope
* **Goal:** Add GitHub Issue intake to the public Evolution Bot's process so that each Evolution session inspects the repository's open GitHub Issues as an external input channel, classifies them by source label, and routes them through the normal Evolution workflow (`review → accepted → implementation → verified → implemented/closed`). This is a **guidance/process change only** — no application code, API clients, GitHub tokens, or database tracking.
* **Target Files/Directories:** `.agents/skills/repository-evolution/SKILL.md`, `AGENTS.md` (§4.1 Skill Routing), `SPECS.md`
* **Out of Scope:**
  - No GitHub Issues API client, token, or intake module in the scraper codebase.
  - No database tracking of Issues.
  - No access to the proprietary repository. A `source:proprietary` Issue is treated as a **public** Issue containing only sanitized technical requirements; do not request or search for proprietary context, and do not assume why the proprietary application needs the capability.

## 2. Dependencies & Prerequisites
- [x] Existing repository-evolution skill (`.agents/skills/repository-evolution/SKILL.md`)
- [x] `AGENTS.md` §4.1 Skill Routing table

## 3. Implementation Units (Execution Order)
*Implement in logical order of foundational dependencies first, regardless of list position.*

- [x] **Unit 1: GitHub Issue intake step in the Evolution skill**
  - [x] Add a "GitHub Issue Intake" lifecycle step to `.agents/skills/repository-evolution/SKILL.md` so every Evolution session checks relevant open Issues
  - [x] Add a "GitHub Issue Intake" section documenting: source labels (`source:proprietary` / `source:human` / `source:community` / `source:automated`), the intake→classify→decide flow, and the Issue lifecycle (`status:review` → `status:accepted` → `status:implemented`/close)
  - [x] Document that the Evolution Bot uses its **existing GitHub/MCP capabilities** to read and update Issues — no new API clients or tokens
  - [x] Document the `source:proprietary` boundary (treat as public Issue; no proprietary access)

- [x] **Unit 2: AGENTS.md pointer**
  - [x] Add a pointer in `AGENTS.md` §4.1 (Skill Routing) noting that the Evolution skill includes GitHub Issue intake

- [x] **Unit 3: Verification**
  - [x] Confirm the Evolution skill and `AGENTS.md` are internally consistent and reference live paths
  - [x] Confirm no application code was added to `scraper/`

## 4. Verification Criteria
*Task is complete only when verified by an observable signal.*

* **Build Command:** `uv sync`
* **Test Command:** `uv run --extra dev pytest`
* **Expected Observable Behavior:**
  - `.agents/skills/repository-evolution/SKILL.md` contains a GitHub Issue intake lifecycle step and section
  - `AGENTS.md` §4.1 references GitHub Issue intake in the Evolution skill
  - The Issue lifecycle (`review → accepted → implementation → verified → implemented/closed`) and the "Issue accepted ≠ Issue implemented" distinction are documented
  - No new files under `scraper/` and no GitHub API/token code added
  - Existing tests still pass (`uv run --extra dev pytest`)

## 5. Compatibility
- Preserve existing public APIs unless specified.
- Preserve backward compatibility unless explicitly waived.
- GitHub Issues are an **input channel** to the Evolution process, not automatic instructions; the Evolution Bot does not implement every Issue.
  - The public wing has no dependency on the proprietary repository (dependency direction remains Proprietary → Public).

---

# Spec: Switch OLX Search Base to the Laptops-Only Category

## 1. Objective & Scope
* **Goal:** Switch the scraper's search base from the broad "Computers & Accessories" OLX category (`laptops-computers-accessories_c443`, which mixes laptops with RAM, GPUs, SSDs, mice, chargers, tablets, and other accessories) to the dedicated "Laptops" category (`laptops_c708203`, which contains only laptop listings). Refactor the category lookup into an extensible `CATEGORIES` dict in `scraper/config.py` so a future scraper for a different category is a config-only change. Closes GitHub Issue #1.
* **Target Files/Directories:** `scraper/config.py`, `scraper/runner.py`, `scraper/cli.py`, `tests/test_runner.py`, `.agents/skills/olx-scraping.md`, `learnings/pending/2026-08-29-category-hierarchy-before-keywords.md`
* **Out of Scope:**
  - Defensive post-fetch title filtering (trust the category; the Laptops category returns 100% laptop listings)
  - Adding new categories beyond the `laptops` entry (only the dict shape is introduced; the dict has one key)
  - Changing the SQLite schema or item_id semantics (item IDs come from OLX item pages, not the search URL)

## 2. Dependencies & Prerequisites
- [x] Existing MVP + pagination specs (all prior units complete and checked off)
- [x] Confirmed via live `web_fetch` that `https://www.olx.com.pk/laptops_c708203/q-laptop` returns 25,780 laptop-only listings, and that city-scoped URLs (`.../islamabad_g4060615/laptops_c708203/q-laptop` and `.../rawalpindi_g4060681/laptops_c708203/q-laptop`) return 2,458 and 2,099 laptop-only listings respectively
- [x] GitHub MCP server available for resolving Issue #1

## 3. Implementation Units (Execution Order)
*Implement in logical order of foundational dependencies first, regardless of list position.*

- [x] **Unit 1: Config refactor — `CATEGORIES` dict**
  - [x] Replace `LAPTOPS_CATEGORY_PATH` in `scraper/config.py` with `CATEGORIES = {"laptops": "laptops_c708203"}`
  - [x] Update inline example URL in the docstring to use `laptops_c708203` and `q-laptop`
  - [x] Update the `DEFAULT_CITIES` example URL to use the new category
  - [x] Change `SEARCH_QUERY` from `"q-laptops"` to `"q-laptop"` (the new category's working query, verified live)

- [x] **Unit 2: Runner + CLI wiring**
  - [x] Update `build_search_url` in `scraper/runner.py` to accept `category: str = "laptops"` and read `config.CATEGORIES[category]`; raise `KeyError` on unknown category
  - [x] Add `category: str = "laptops"` to `run()` and pass it into `build_search_url` inside the pagination loop
  - [x] Add `--category` flag to `scraper/cli.py` with `choices=list(config.CATEGORIES.keys())` and default `"laptops"`; thread through to `run()`

- [x] **Unit 3: Tests + verification + Issue resolution**
  - [x] Add `test_build_search_url_uses_laptops_c708203` to `tests/test_runner.py` (asserts `laptops_c708203` is in the URL and `c443` / `laptops-computers-accessories` are not — regression guard)
  - [x] Add `test_build_search_url_unknown_category_raises` to `tests/test_runner.py` (asserts `KeyError` on unknown category)
  - [x] Add `test_build_search_url_round_trips_every_documented_category` to `tests/test_runner.py` (defense against future config drift)
  - [x] Update `.agents/skills/olx-scraping.md` to document `laptops_c708203` as the new base category and update the URL examples
  - [x] Add `learnings/pending/2026-08-29-category-hierarchy-before-keywords.md` (Evolution Candidate: destination SKILL, priority Medium)
  - [x] Confirm full test suite passes (`uv run --extra dev pytest` → 32/32)
  - [x] Post resolution comment on GitHub Issue #1 and close it as resolved-by-category-switch

## 4. Verification Criteria
*Task is complete only when verified by an observable signal.*

* **Build Command:** `uv sync`
* **Test Command:** `uv run --extra dev pytest`
* **Expected Observable Behavior:**
  - `python -c "from scraper.runner import build_search_url; print(build_search_url('islamabad_g4060615', 1))"` produces a URL containing `laptops_c708203`, `page=1`, and `sorting=desc-creation` (and not `c443`)
  - `python -m scraper --help` lists `--category` with default `laptops`
  - `uv run python -m scraper --hours 24` produces a SQLite DB whose rows are 100% laptop listings (no RAM, SSD, mouse, charger, tablet, iPad, etc.)
  - All 32 tests pass
  - GitHub Issue #1 is closed with a comment explaining the category switch

## 5. Compatibility
- Preserve existing public APIs unless specified.
- Preserve backward compatibility unless explicitly waived.
- The change to `LAPTOPS_CATEGORY_PATH` is an internal constant removal; no external caller (CLI, README, docs) referenced it. The new `--category` flag defaults to `laptops`, so existing CLI invocations produce the new URL automatically.
- The scraper remains polite to OLX: the `delay` flag and retry/backoff behavior are unchanged.

---

# Spec: Release 1.0.0 — Seller Name, Docker, CI/CD, Ubuntu Deployment

## 1. Objective & Scope
* **Goal:** Ship **Release 1.0.0** of the OLX laptop scraper as a Dockerized, CI/CD-published, systemd-scheduled service on the Ubuntu mini PC. The release bundles four deliverables that ship together as one versioned release:
  1. **Seller-name capture** — record the seller's display name (visible on the OLX item page) as a new `seller_name` column in `listings`.
  2. **Docker image** — a single, reproducible `Dockerfile` that packages the scraper and its dependencies (no `uv` or `pip` required at runtime).
  3. **CI/CD pipeline** — GitHub Actions builds the Docker image on every push to `main` and on every `v*` tag, runs the test suite as the gate, and pushes the image to `ghcr.io/fe4rlesscloak/laptop-tracker`. The workflow is intentionally small and heavily commented so it doubles as a learning artifact for the developer.
  4. **Ubuntu deployment** — `systemd` service + timer files the developer copies to `/etc/systemd/system/` on the Ubuntu mini PC; the timer fires the `docker run` command twice a day with `Persistent=true` so missed runs after a reboot fire immediately. Data + exports persist on a named Docker volume.
* **Target Files/Directories:** `scraper/parsers.py`, `scraper/storage.py`, `scraper/cli.py`, `tests/test_storage.py`, `tests/test_parsers.py`, `tests/test_runner.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.github/workflows/release.yml`, `deploy/systemd/olx-scraper.service`, `deploy/systemd/olx-scraper.timer`, `deploy/README.md`, `README.md`, `AGENTS.md`, `TECH_DEBT.md`, `SPECS.md`
* **Out of Scope:**
  - Anything that requires the proprietary public→proprietary dependency edge to flip. This release stays public-only.
  - The "flag lucrative deals" analysis system (deferred; tracked in `README.md` Roadmap).
  - Image downloads (URLs only, as before).
  - Multi-region / multi-operator configuration (the image is for a single Ubuntu box, single operator; you set `--operator` if and when that lands later).
  - GPU, Kubernetes, Helm, Terraform, or any cloud-provider-specific infra. Plain Docker + systemd is the entire deployment surface.
  - Public-by-default registry settings. The `ghcr.io/fe4rlesscloak/laptop-tracker` package starts private; the developer flips it public (or keeps it private and adds the box's PAT) as a one-time setup step documented in `deploy/README.md`.

## 2. Dependencies & Prerequisites
- [x] GitHub repo `Fe4rlessCloak/Laptop-Tracker` confirmed as the source of truth (verified via `git remote -v`)
- [x] `ghcr.io` package `laptop-tracker` created (or auto-created on first push by GitHub Actions) under the `fe4rlesscloak` namespace
- [x] Ubuntu mini PC reachable from the developer's laptop via SSH; `docker` and `docker compose` (v2) installed; `systemd` available (default on Ubuntu)
- [x] All prior specs (MVP, pagination, GitHub Issue intake, laptops-only category) completed and tests passing — already true at the start of this spec
- [x] Live OLX item page captured and inspected to confirm where `seller_name` appears in the HTML (the parser unit test will use a captured HTML fixture, not a live fetch, so the implementation does not block on a live check — but the implementer should fetch one item page to design the selector before writing the parser)

## 3. Implementation Units (Execution Order)
*Implement in logical order of foundational dependencies first, regardless of list position.*

- [x] **Unit 1: `seller_name` schema + storage**
  - [x] Add `seller_name TEXT` (nullable) to the `listings` table in `scraper/storage.py::_create_schema` — append to the existing columns; do not reorder
  - [x] Add `"seller_name"` to `LISTING_COLUMNS` so CSV/JSON exports include it (appended at the end to preserve column order for existing exports)
  - [x] Add `"seller_name": listing.get("seller_name")` to `_listing_to_row` and to `_row_to_listing` so the field round-trips through the DB
  - [x] Add a unit test in `tests/test_storage.py` verifying: (a) a listing with `seller_name` round-trips through `upsert_listing` + `fetch_all`, (b) a listing without `seller_name` stores and reads back as `None`, (c) the `seller_name` column appears in CSV export output

- [x] **Unit 2: `seller_name` parser**
  - [x] Add `_find_seller_name(soup)` to `scraper/parsers.py` — returns the seller display name (str) or `None`. Implementation: inspect the captured OLX item page HTML to identify the selector, prefer a stable selector (e.g., an element with the user's display name in the seller card), fall back to `None` rather than guessing. Document the chosen selector in a comment so future implementers can update it if OLX redesigns.
  - [x] Call `_find_seller_name` from `parse_item_detail` and set `listing["seller_name"]` if found (do NOT overwrite an existing value with `None` — keep the existing value if both are present, since this lets us re-scrape for description without dropping seller_name if the new selector misses)
  - [x] Add unit tests in `tests/test_parsers.py` using a captured HTML fixture: (a) seller name is extracted when present, (b) returns `None` when absent, (c) the parser is robust to whitespace/empty

- [x] **Unit 3: README + AGENTS snapshot update (so future sessions know the project is now Docker-first)**
  - [x] Update `README.md` to add: a "Production (Docker on Ubuntu mini PC)" section pointing at `deploy/README.md`; a "CI/CD" section explaining the `ghcr.io/fe4rlesscloak/laptop-tracker` flow in plain language; a CI badge placeholder (`[![Release](https://github.com/Fe4rlessCloak/Laptop-Tracker/actions/workflows/release.yml/badge.svg)](https://github.com/Fe4rlessCloak/Laptop-Tracker/actions/workflows/release.yml)`)
  - [x] Update `AGENTS.md` §1 Project Snapshot: add a "Container Image" line (`ghcr.io/fe4rlesscloak/laptop-tracker:latest`); change the `Run Command` line to show both `uv run python -m scraper` (local dev) and `docker run --rm ghcr.io/fe4rlesscloak/laptop-tracker:latest` (production); add a "Deploy Target" line (`Ubuntu mini PC via systemd timer + Docker`)

- [x] **Unit 4: Dockerfile**
  - [x] Write a `Dockerfile` (multi-stage not needed; ~15 lines): `FROM python:3.11-slim` as the base; `WORKDIR /app`; copy `pyproject.toml` and `scraper/`; `pip install --no-cache-dir .` (use `pip` in the image for simplicity; the host uses `uv` for dev but the image doesn't need `uv`); set the entrypoint to `python -m scraper` so `docker run --rm <image> --hours 24 --export csv json` works the same as the local invocation
  - [x] Write a `.dockerignore` that excludes `data/`, `.git/`, `__pycache__/`, `.pytest_cache/`, `.venv/`, `.commandcode/`, `learnings/`, `.agents/`, `*.egg-info/`, `tests/` (tests run in CI, not in the runtime image), `deploy/` (host-side systemd files don't belong in the image)
  - [x] Add a manual verification note in the Dockerfile comment: `docker build -t laptop-tracker:dev . && docker run --rm -v laptop-tracker-data:/app/data laptop-tracker:dev --hours 1` should run end-to-end against a fresh container

- [x] **Unit 5: docker-compose.yml**
  - [x] Write a `docker-compose.yml` with a single `services.scraper` entry that uses `image: ghcr.io/fe4rlesscloak/laptop-tracker:latest`, sets `pull_policy: always` (so the box always runs the latest pushed image), defines a named volume `laptop-tracker-data:/app/data`, and sets the default `command: ["--hours", "24", "--export", "csv", "json"]` (overridable from the systemd unit or by `docker compose run scraper <other-flags>`)
  - [x] Document the volume at the top of the file: the SQLite DB and CSV/JSON exports persist in this named volume so they survive container restarts

- [x] **Unit 6: `.github/workflows/release.yml` (CI/CD — heavily commented for learning)**
  - [x] Triggers: `push` to `main`, `push` of tags matching `v*` (e.g., `v1.0.0`), and `workflow_dispatch` (manual run from the Actions tab)
  - [x] Jobs: a single `build-and-push` job running on `ubuntu-latest`
  - [x] Steps (in order, each commented inline):
    1. `actions/checkout@v4` — clone the repo
    2. `actions/setup-python@v5` with `python-version: '3.11'` and `cache: 'pip'` — for the test step
    3. `pip install -e '.[dev]'` — install the package + pytest
    4. `pytest -q` — gate: if tests fail, the workflow stops here and no image is pushed
    5. `docker/login-action@v3` with `registry: ghcr.io` and `username: ${{ github.actor }}` — uses the workflow's automatic `GITHUB_TOKEN` (no PAT needed); the workflow also needs `packages: write` permission declared at the job level
    6. `docker/metadata-action@v5` with `images: ghcr.io/fe4rlesscloak/laptop-tracker` and `tags: type=sha,format=short` + `type=raw,value=latest` — produces multi-tag metadata so the box can pull `:latest` (rolling) or `:sha-abc1234` (immutable per-build)
    7. `docker/build-push-action@v5` with `push: true` and the metadata as tags
  - [x] Add inline YAML comments above each step explaining what it does in plain English (this workflow doubles as a learning artifact)
  - [x] Add a top-of-file comment block explaining the full flow: "On push to main → tests run → image built → pushed to ghcr.io. The Ubuntu box pulls the new image on its next scrape run."
  - [x] Declare top-level `permissions: contents: read, packages: write` so `GITHUB_TOKEN` can publish to ghcr.io

- [x] **Unit 7: Ubuntu deployment assets (`deploy/`)**
  - [x] `deploy/systemd/olx-scraper.service` — a Type=oneshot systemd service. ExecStart runs `docker run --rm --pull=always -v laptop-tracker-data:/app/data ghcr.io/fe4rlesscloak/laptop-tracker:latest --hours 24 --export csv json`. After the container exits, the named volume keeps the SQLite DB + exports. (The volume is created on first run; subsequent runs reuse it.)
  - [x] `deploy/systemd/olx-scraper.timer` — fires the service twice a day at 09:00 and 21:00 local time. Set `Persistent=true` so missed runs (e.g., the box was off) fire immediately on next boot. Set `AccuracySec=1m` to avoid wake-the-box-from-sleep issues.
  - [x] `deploy/README.md` — one-time setup instructions, in plain language: (1) SSH into the box, (2) `sudo docker login ghcr.io` with a PAT that has `read:packages` scope (one-time; credentials persist in `~/.docker/config.json`), (3) `sudo docker volume create laptop-tracker-data`, (4) copy the two systemd files to `/etc/systemd/system/`, (5) `sudo systemctl daemon-reload && sudo systemctl enable --now olx-scraper.timer`, (6) verify with `systemctl list-timers olx-scraper.timer` and `journalctl -u olx-scraper.service -n 50`. Include a "Rollback" section: change `latest` to a specific tag in `olx-scraper.service` and `sudo systemctl daemon-reload`. Include a "Where the data lives" note pointing at the named volume and the `docker volume inspect laptop-tracker-data` command.

- [x] **Unit 8: TECH_DEBT entry (intentional compromise)**
  - [x] Create `TECH_DEBT.md` from `.agents/templates/TECH_DEBT.template.md` if it does not exist; otherwise append an entry
  - [x] Record: the `_find_seller_name` selector is best-effort against the current OLX Pakistan item page HTML structure. If OLX redesigns the seller card, `seller_name` will silently become NULL for affected listings. The failure mode is graceful (the listing still has title, price, location, description, etc.) but the field will need a selector update. Revisit this if/when a real run shows a long stretch of NULL `seller_name` values.

- [x] **Unit 9: Verification gate**
  - [x] All 32 existing tests still pass + new seller_name tests pass (≥ 35 total)
  - [x] `docker build -t laptop-tracker:dev .` succeeds locally
  - [x] `docker run --rm -v laptop-tracker-data:/app/data laptop-tracker:dev --hours 1 --export csv json` runs end-to-end against a fresh container (this is the "release gate" check — the developer does this once before tagging v1.0.0)
  - [x] `.github/workflows/release.yml` passes `actionlint` or `yamllint` (no schema errors)
  - **Evolution clarification (2026-10-04):** Static workflow validation does not prove third-party action runtime behavior. Future workflow changes must inspect the selected release's input schema and release notes, justify version selection, and verify the actual hosted run before claiming publication success. This clarifies verification guidance; it does not assert a new check was performed for this historical release.
  - [x] `systemd-analyze verify deploy/systemd/olx-scraper.service` and `... olx-scraper.timer` succeed (the developer runs these locally if `systemd-analyze` is installed; otherwise by inspection)
  - [x] The README's CI badge URL resolves to the right repo

## 4. Verification Criteria
*Task is complete only when verified by an observable signal.*

* **Build Command (local dev):** `uv sync`
* **Test Command:** `uv run --extra dev pytest`
* **Build Command (image):** `docker build -t laptop-tracker:dev .`
* **Run Command (local):** `uv run python -m scraper --hours 24 --export csv json`
* **Run Command (production):** `sudo systemctl start olx-scraper.service` (or wait for the timer)
* **CI Command:** push to `main` or push a `v*` tag; observe the `Release` workflow in the GitHub Actions tab; verify the image appears under `https://github.com/Fe4rlessCloak/Laptop-Tracker/pkgs/container/laptop-tracker`
* **Expected Observable Behavior:**
  - `uv run --extra dev pytest` reports **35+ tests, all passing** (32 existing + ≥ 3 new for `seller_name`)
  - `docker build -t laptop-tracker:dev .` produces a working image without errors
  - `docker run --rm -v laptop-tracker-data:/app/data laptop-tracker:dev --hours 1 --export csv json` exits 0 and creates a SQLite DB + CSV + JSON inside the named volume (`docker volume inspect laptop-tracker-data` shows the files)
  - Pushing to `main` triggers the GitHub Actions `Release` workflow; on green, the image lands at `ghcr.io/fe4rlesscloak/laptop-tracker:latest` (verifiable by `docker manifest inspect ghcr.io/fe4rlesscloak/laptop-tracker:latest` from any machine after the workflow completes)
  - On the Ubuntu mini PC, after one-time setup, `systemctl list-timers olx-scraper.timer` shows the next scheduled run; `journalctl -u olx-scraper.service -n 50` shows the most recent run's logs (the same per-page/per-listing log format the CLI already prints)
  - Rolling back to a previous version = change `:latest` to a specific tag in `olx-scraper.service`, `sudo systemctl daemon-reload`, run the service. Verified by `docker inspect` on the running container showing the pinned tag.
  - `TECH_DEBT.md` exists and contains the `seller_name` selector fragility entry
  - `AGENTS.md` §1 Project Snapshot reflects the Docker-first reality (container image, deploy target, both run commands)

## 5. Compatibility
- Preserve existing public APIs unless specified.
- Preserve backward compatibility unless explicitly waived.
- The new `seller_name` column is added at the end of `LISTING_COLUMNS` so existing CSV exports remain compatible (consumers reading by column index are unaffected; consumers reading by header name pick up the new column automatically).
- Adding a new column to an existing SQLite table uses `ALTER TABLE ... ADD COLUMN` if the DB already exists. If the implementer chooses to keep the existing `_create_schema` pattern (which uses `CREATE TABLE IF NOT EXISTS`), existing DBs will be missing the column until the implementer adds a small migration in `_create_schema` (`PRAGMA table_info(listings)` check + `ALTER TABLE` if the column is absent). Document the chosen path in the PR description.
- The `Dockerfile` entrypoint is `python -m scraper` so existing CLI flags work identically inside the container.
- The scraper remains polite to OLX: `DEFAULT_DELAY` and retry/backoff are unchanged.
- No new third-party runtime dependencies — `Dockerfile` uses the stdlib `pip` to install the existing `pyproject.toml` dependencies.

---

# Spec: Persistent Monitoring and Web Reporting UI

## 1. Objective & Scope
* **Goal:** Provide a lightweight, read-only Web UI for browsing/searching laptops fetched today (with price, city, and discovery-date filters) and viewing scraper performance metrics (average latency, P50, P95, P99 / slowest 1%, P99.9 / slowest 0.1%, failure/retry rates, and run history), backed directly by `olx.db` and `monitoring.db` while keeping the scheduled one-shot scraper isolated and unchanged in its listing schema and upsert behavior.
* **Status:** Revised to **Option A** (direct SQLite-backed Python Web UI replacing Grafana, Prometheus, exporter, and snapshot publisher) during Repository Evolution on 2026-11-17. **Unit 1** is complete (`fc4a4cf`); awaiting developer approval before implementing **Units 2–5**. Preceding specifications are historical.
* **Target Files/Directories:** [scraper/](scraper/), [tests/](tests/), [pyproject.toml](pyproject.toml), [uv.lock](uv.lock), [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml), [deploy/](deploy/), [README.md](README.md). New instrumentation, web UI modules, HTML templates/assets, and tests belong within those directories. Do not modify operational guidance during implementation.
* **Out of Scope:** Grafana, Prometheus, Pushgateway, or custom metrics exporter services; atomic reporting-snapshot publisher; arbitrary SQL editor; browser-based database writes; user login/auth for this initial private-network release (see [DEBT-003](TECH_DEBT.md)); OLX posting-date filters; physical-laptop/repost deduplication; database-operation timing; host-resource monitoring; notifications/alerting; public internet exposure; HTTPS/certificate infrastructure for this release; changes to scraper politeness or scheduled frequency.

### Agreed Reporting & Search Semantics
* **Unique listings vs. observations:** A unique listing is a distinct OLX `item_id` (not necessarily a distinct physical laptop). An observation is one processed listing encounter (including repeats across runs), not one HTTP retry. Retain partial listings after detail-fetch failure as before, and distinguish `stored` vs. `failed` observations.
* **Listings GUI:**
  * Default view shows laptops **first discovered today** (using `Asia/Karachi` calendar date from `monitoring.db` `discoveries`), with a view mode toggle for **Discovered today**, **Seen today** (observed today in `monitoring.db` `observations`), and **All time / Custom discovery date range**.
  * Search & filters: keyword search (case-insensitive substring match over `title` and `description`), `city` (All or one configured city), numeric `min_price` / `max_price` in PKR (using latest stored `price_numeric` from `olx.db`; listings with unknown price are excluded when numeric bounds are set and otherwise shown as unknown), sort order (newest discovered, price low-to-high, price high-to-low), and bounded pagination.
  * Each listing row/card displays `title`, `price`, `city`, `seller_name`, discovery date (and latest seen timestamp), and a clickable external OLX link (`item_url`). Unknown discovery dates are included in all-time totals and clearly labeled rather than shown as today.
  * Invalid/reversed filter ranges or empty datasets must return clean validation/empty states, never 500s or unsafe SQL interpolation.
* **Timezone contract:** Store timestamps in UTC; use `Asia/Karachi` for calendar dates and "today" by default with start-inclusive / end-exclusive boundaries. Retain the approved `UTC+05:00` fallback for post-2009 dates when `tzdata` is absent; see [DEBT-002](TECH_DEBT.md).

### Historical Data & Schema Boundary
* Preserve `olx.db` (`listings` columns, export column order, latest-scrape upsert meaning). Do not add discovery columns or monitoring tables to `olx.db`.
* Keep `monitoring.db` isolated (Unit 1 complete: `discoveries`, `observations`, `runs`, `archive_imports`, `counters`, `schema_meta`, plus Unit 2 `request_events`).
* Historical daily exports remain operator-imported via `python -m scraper.monitoring import ...` (idempotent, `scraped_at` only, never `posted_at`). Show a short note in the UI when historical archive estimates are present ("Historical discovery dates include estimates reconstructed from daily exports"). Do not bake production data or exports into images, tests, or commits.

### Performance Metrics Contract
* Measure every HTTP attempt in `fetcher.py` (including failed/timed-out attempts) with monotonic duration (`duration_ms`), excluding politeness sleep (`sleep_between`) and retry backoff. Record bounded fields per attempt: `run_id`, `recorded_at` (UTC), `page_type` (`search` | `detail`), `city`, `attempt_number`, `status_code` (nullable), `outcome` (`ok` | `transient_http` | `http_error` | `request_error`), and `duration_ms`. Never store full URLs, listing IDs, seller names, or raw exception strings in performance rows.
* Persist `request_events` and `runs` to `monitoring.db` during/after runs so completed work survives abrupt exits; monitoring DB errors must log a warning and never prevent `olx.db` listing ingestion or CSV/JSON export. Keep imported archive observations out of HTTP metrics.
* **Performance GUI:** Window selector (`Last run`, `Last 24h`, `Last 7 days`, `Last 30 days`, `All time`), displaying overall and `search` vs. `detail` breakdowns:
  * Request sample count, **Average (mean) latency**, **P50 (median)**, **P95**, **P99 (slowest 1% / "1% low")**, and **P99.9 (slowest 0.1% / "0.1% low")** computed directly from persisted `request_events` durations (not histogram bucket guesses). Display "No data" when sample count is 0.
  * **Attempt failure rate** (`unsuccessful attempts / total attempts`), **Final-fetch failure rate** (`exhausted/finally failed logical fetches / total logical fetches`), and **Retries** (`attempts with attempt_number > 1`). Recovered retries count as attempt failures, not final-fetch failures.
  * **Run History table** (`runs` table): `started_at`, `completed_at`, duration, `outcome` (`completed` / `completed-with-fetch-errors` / `failed` / `incomplete`), and `listings_seen` / `new_count` / `stored_count` / `repeat_count` / `skipped_count` / `error_count`. Include stale-run warning indicator when no completed run occurred in the last 26 hours (configurable).

### Architecture, Persistence & Access
* **Two runtime pieces sharing `laptop-tracker-data`:**
  1. **Scraper (existing one-shot systemd timer):** Remains `ENTRYPOINT ["python", "-m", "scraper"]` and continues running even if the Web UI container is stopped. Accepts additive `--monitoring-db` option (defaulting to `config.DEFAULT_MONITORING_DB_PATH`).
  2. **Web UI service (`python -m scraper.web`):** Lightweight Python ASGI app (FastAPI + Uvicorn, pinned in `pyproject.toml` / `uv.lock`) reusing the same Docker image (`ghcr.io/fe4rlesscloak/laptop-tracker:latest`) via `entrypoint` override in [docker-compose.yml](docker-compose.yml), `restart: unless-stopped`, and a healthcheck.
* **Read-only query safety:** Web UI opens `olx.db` and `monitoring.db` with SQLite read-only mode (`?mode=ro` + `PRAGMA query_only = ON` and busy timeout) and handles missing/uninitialized DB files gracefully on fresh startup. Never expose write routes or raw SQL parameters. Verify concurrent WAL access under container volume permissions without privileged/root workarounds.
* **Private exposure & intentional no-auth trade-off:** Bind the Web UI port only to configurable private host IP(s) (LAN / Tailscale, never wildcard `0.0.0.0` by default). No login/authentication in this initial read-only release on the trusted private network ([DEBT-003](TECH_DEBT.md)); document the unencrypted HTTP + no-auth LAN risk and prefer Tailscale access when feasible.
* **Volume & retention:** Preserve literal `laptop-tracker-data` named volume in [docker-compose.yml](docker-compose.yml). Retain `discoveries`, `observations`, `runs`, and `request_events` indefinitely initially (~tens of MB/year); document disk usage inspection and consistent SQLite backup/restore in [deploy/README.md](deploy/README.md).

## 2. Dependencies & Prerequisites
- [x] Unit 1 durable monitoring model and historical import completed and verified (`fc4a4cf`, 75 tests passing).
- [x] GitHub intake completed on 2026-11-17: 0 open issues on `Fe4rlessCloak/Laptop-Tracker`.
- [x] Developer chose Option A (lightweight read-only Web UI, no authentication on private LAN/Tailscale bind for now) on 2026-11-17.
- [x] Verify pinned FastAPI/Uvicorn (and template/HTTP test client) dependency compatibility with Python `>=3.10` and `python:3.11-slim` (amd64/arm64) in `pyproject.toml` and `uv.lock` before Unit 3.
- [ ] Operator provides LAN/Tailscale bind address(es) and deployment host access during Unit 5 target verification.

## 3. Implementation Units (Execution Order)
*Implement in logical order of foundational dependencies first, regardless of list position.*

- [x] **Unit 1: Durable monitoring model and historical import**
  - [x] Add isolated monitoring storage and explicit archive import under [scraper/](scraper/), with compatible local defaults and configurable paths; preserve listing schema/upsert/export semantics.
  - [x] Implement immutable discovery records, idempotent import/reconciliation, observation identifiers, run lifecycle, cumulative metrics, schema migration for monitoring only, and restart/recovery consistency.
  - [x] Add synthetic-fixture tests for repeated observations, archived estimates, missing history, duplicate snapshots/imports, timezone boundaries, and storage failures without using production data.
  - [x] Resolve [REV-001 and REV-002](REVIEWER_FINDINGS.md): never substitute posting time for discovery/observation time; preserve immutable live discovery dates and allow only the explicit archive reconciliation permitted above. Add regression tests before fixes.
  - [x] Verify date-boundary behavior with timezone data unavailable for current supported dates; document the older-date limit in operator guidance.
- [x] **Unit 2: Scraper instrumentation & request latency storage**
  - [x] Add `request_events` table + schema migration and query/percentile helpers (mean, P50, P95, P99, P99.9, failure/retry aggregates) to [scraper/monitoring.py](scraper/monitoring.py), keeping existing tables/semantics intact.
  - [x] Instrument [scraper/fetcher.py](scraper/fetcher.py) and [scraper/runner.py](scraper/runner.py) (plus additive `--monitoring-db` flag in [scraper/cli.py](scraper/cli.py)) to record `runs`, `discoveries`, `observations`, and per-attempt `request_events`, preserving retry/delay behavior, injected test fetchers, and non-blocking degradation if `monitoring.db` writes fail.
  - [x] Add synthetic tests covering recovered retries, exhausted fetches, partial/fatal/unfinished runs, exact latency percentile math (including P99 and P99.9), isolated monitoring DB failures not breaking `olx.db`/exports, and repeat-run discovery/observation counts.
- [x] **Unit 3: Read-only Web UI & JSON/HTML endpoints**
  - [x] Add pinned Web UI dependencies (`fastapi`, `uvicorn`, `jinja2` or equivalent minimal stdlib-compatible template rendering, `httpx` in dev if needed) to [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock).
  - [x] Implement [scraper/web.py](scraper/web.py) (with clean HTML/CSS/JS views and JSON API routes) exposing:
    - Listings view & search/filter controls (`Discovered today` / `Seen today` / `All`, keyword search, `city`, `min_price`/`max_price` PKR, date range, sort, pagination, OLX links, archive-estimate note).
    - Performance overview (window selector, sample counts, Average / P50 / P95 / P99 / P99.9 overall and `search` vs. `detail`, attempt/final failure rates, retries, Run History table, 26h stale-run warning).
  - [x] Enforce read-only SQLite access (`?mode=ro` + `PRAGMA query_only = ON`), parameterized queries, safe HTML escaping, invalid-input handling, and graceful empty/bootstrap states when DBs are absent or empty.
  - [x] Add comprehensive Web UI tests covering date/city/price/search filters, today boundaries in `Asia/Karachi`, unknown prices/dates, percentile edge cases (0 samples, small samples, 1,000+ samples for P99.9), read-only enforcement, and missing-DB bootstrap states.
- [x] **Unit 4: Container deployment & operator documentation**
  - [x] Preserve `ENTRYPOINT ["python", "-m", "scraper"]` in [Dockerfile](Dockerfile) and verify `python -m scraper.web` runs inside the built image.
  - [x] Extend [docker-compose.yml](docker-compose.yml) with the `web` service sharing the existing literal `laptop-tracker-data` volume, `restart: unless-stopped`, healthcheck, configurable private bind address (no wildcard default), and non-destructive coexistence with `deploy/systemd/olx-scraper.service`.
  - [x] Update [README.md](README.md) and [deploy/README.md](deploy/README.md) with Web UI usage, private bind configuration, LAN/no-auth HTTP security note ([DEBT-003](TECH_DEBT.md)), historical archive import, disk/backup/restore, and data-preserving rollback.
- [ ] **Unit 5: Observable verification**
  - [x] Run full `uv run --extra dev pytest` suite, `docker build -t laptop-tracker:dev .`, and `docker compose config` validation.
  - [x] Run an end-to-end synthetic container verification: execute scraper runs into a shared volume (with repeated listings and injected retries/failures), verify the `web` service serves accurate filtered listings and exact Average / P99 / P99.9 performance stats read-only, and verify state survives container recreation.
  - [ ] Verify private LAN/Tailscale reachability, no unintended public port exposure, and existing systemd timer compatibility on the mini PC (or explicitly document target-host checks pending operator execution).

## 4. Verification Criteria
*Task is complete only when verified by an observable signal.*
* **Build Command:** `uv sync --extra dev` and `docker build -t laptop-tracker:dev .` and `docker compose config`.
* **Test Command:** `uv run --extra dev pytest`
* **Expected Observable Behavior:**
  - Two synthetic scrape runs with repeated IDs and injected retries/failures produce exact discovery-today vs. seen-today counts in the Web UI, unchanged `olx.db` schema/CSV/JSON exports, recovered retries counted in attempt failures (not final-fetch failures), and accurate Average / P50 / P95 / P99 / P99.9 latencies.
  - Price/city/keyword/date filters match independently queried fixture rows; unknown prices are excluded when numeric bounds are active; invalid ranges render clean validation/empty states.
  - Unfinished/crashed runs stay visible in Run History; monitoring DB failures do not stop listing ingestion/exports.
  - The `web` service runs from the shared image in read-only DB mode, cannot mutate SQLite files, handles missing/empty DBs cleanly, binds only to configured private address(es), and retains all history across container recreation.

## 5. Compatibility
- Preserve existing public APIs, CLI defaults, `olx.db` schema/upsert semantics, `seller_name` extraction, export column order, delays, retries, and pagination rules.
- Synthetic data only in tests; never commit production DBs, daily exports, or secrets.
- Implementation may check off this specification, write blockers/learnings, and modify scoped application/deployment/user documentation only; operational guidance ownership remains unchanged.
- No implementation of **Units 2–5** begins until the developer explicitly approves this revised specification.
