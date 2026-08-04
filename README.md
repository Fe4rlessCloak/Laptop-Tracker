# Laptop Tracker — OLX Pakistan Scraper

A Python CLI scraper that fetches recent **laptop listings** from [OLX Pakistan](https://www.olx.com.pk/) for the **Islamabad** and **Rawalpindi** areas, stores them in a local **SQLite** database, and exports to **CSV/JSON**.

The goal is to reliably capture the freshest listings so you can later flag the most lucrative deals (a future, non-ML analysis step).

## Features

- **City-scoped scraping** — targets Islamabad and Rawalpindi only (configurable).
- **Configurable time window** — look back 12–24 hours (or any value) to catch fresh listings.
- **Rich data** — title, price (normalized), location, relative posting time, description, image URLs (text only — no image downloads), and the "Featured" flag.
- **SQLite storage with upserts** — repeated runs insert new listings and update existing ones by OLX item ID, building a clean history over time.
- **CSV/JSON export** — easy viewing and downstream analysis.
- **Polite fetching** — realistic browser User-Agent, configurable delay between requests, and retry/backoff on transient failures.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (package manager)

## Setup

```bash
uv sync
```

## Usage

```bash
# Scrape the last 24 hours and export to CSV + JSON
uv run python -m scraper --hours 24 --export csv json

# Scrape the last 12 hours, JSON only
uv run python -m scraper --hours 12 --export json

# Custom database path and request delay
uv run python -m scraper --db data/olx.db --delay 3
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--cities` | `islamabad rawalpindi` | Cities to scrape (keys in `scraper/config.py`) |
| `--hours` | `24` | Look-back window in hours |
| `--export` | *(none)* | Export formats: `csv`, `json`, or both |
| `--db` | `data/olx.db` | Path to the SQLite database |
| `--delay` | `2.0` | Delay in seconds between requests |

## Output

- **SQLite database** at `data/olx.db` (default) — the source of truth.
- **Exports** written to `data/listings.csv` and/or `data/listings.json`.

Each listing stores: `item_id`, `title`, `price`, `price_numeric`, `currency`, `location`, `city`, `relative_time`, `posted_at`, `description`, `image_urls`, `item_url`, `is_featured`, `scraped_at`.

## Tests

```bash
uv run --extra dev pytest
```

## Project structure

```
scraper/
  config.py     Central configuration (cities, time window, delay, URLs)
  storage.py    SQLite schema, upsert logic, CSV/JSON export
  fetcher.py    Polite HTTP client (User-Agent, delay, retry/backoff)
  parsers.py    HTML parsing, price normalization, relative-time parsing
  runner.py     Orchestrates fetch → filter → enrich → upsert → export
  cli.py        Command-line entry point
tests/          Unit + integration tests
SPECS.md        Active specification (all units complete)
```

## Roadmap (future work)

- Deploy to a home server (Ubuntu mini PC).
- Automated scheduling (cron/systemd) for daily or twice-daily runs.
- A "flag lucrative deals" analysis system (no ML).
