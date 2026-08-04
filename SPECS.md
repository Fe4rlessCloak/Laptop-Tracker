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
