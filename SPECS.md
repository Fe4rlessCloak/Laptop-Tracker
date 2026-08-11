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
