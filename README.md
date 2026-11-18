# Laptop Tracker — OLX Pakistan Scraper

[![Release](https://github.com/Fe4rlessCloak/Laptop-Tracker/actions/workflows/release.yml/badge.svg)](https://github.com/Fe4rlessCloak/Laptop-Tracker/actions/workflows/release.yml)
[![Image](https://img.shields.io/badge/ghcr.io-fe4rlesscloak%2Flaptop--tracker-blue)](https://github.com/Fe4rlessCloak/Laptop-Tracker/pkgs/container/laptop-tracker)

A Python CLI scraper that fetches recent **laptop listings** from [OLX Pakistan](https://www.olx.com.pk/) for the **Islamabad** and **Rawalpindi** areas, stores them in a local **SQLite** database, and exports to **CSV/JSON**. Ships as a single Docker image that runs on the Ubuntu mini PC twice a day via a systemd timer, with GitHub Actions building and publishing each release.

The goal is to reliably capture the freshest listings so you can later flag the most lucrative deals (a future, non-ML analysis step).

## Features

- **City-scoped scraping** — targets Islamabad and Rawalpindi only (configurable).
- **Configurable time window** — look back 12–24 hours (or any value) to catch fresh listings.
- **Rich data** — title, price (normalized), location, relative posting time, description, image URLs (text only — no image downloads), the "Featured" flag, and the **seller's display name**.
- **SQLite storage with upserts** — repeated runs insert new listings and update existing ones by OLX item ID, building a clean history over time. Legacy databases are auto-migrated to add new columns.
- **CSV/JSON export** — easy viewing and downstream analysis.
- **Polite fetching** — coherent browser request headers (a bare Chrome `User-Agent` gets a `503` from OLX), configurable delay between requests, retry/backoff on transient failures, and detail pages fetched only for listings that are not already enriched, capped at `MAX_DETAIL_FETCHES_PER_RUN = 60` per run. A steady-state run is a handful of search pages plus genuinely new listings.
- **CI/CD** — every push to `main` runs tests, builds the image, and pushes it to `ghcr.io`. The Ubuntu box pulls the new image on its next scheduled run.
- **Scheduled deploy** — a systemd timer runs the container twice a day (09:00 and 21:00 local), with `Persistent=true` so missed runs after a reboot fire immediately.

## Requirements

**For local development:**
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (package manager)

**For production (Ubuntu mini PC):**
- Docker + docker compose v2
- systemd (default on Ubuntu)

## Local development

### Setup

```bash
uv sync
```

### Usage

```bash
# Scrape the last 24 hours and export to CSV + JSON
uv run python -m scraper --hours 24 --export csv json

# Scrape the last 12 hours, JSON only
uv run python -m scraper --hours 12 --export json

# Custom database path and request delay
uv run python -m scraper --db data/olx.db --delay 3

# Run the read-only Web UI locally (http://127.0.0.1:8000)
uv run python -m scraper.web

# Import historical daily exports into monitoring.db (explicit operator action)
uv run python -m scraper.monitoring --db data/monitoring.db import data/listings-2026-10-04.json
uv run python -m scraper.monitoring --db data/monitoring.db stats
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--cities` | `islamabad rawalpindi` | Cities to scrape (keys in `scraper/config.py`) |
| `--hours` | `24` | Look-back window in hours |
| `--export` | *(none)* | Export formats: `csv`, `json`, or both |
| `--db` | `data/olx.db` | Path to the SQLite database |
| `--monitoring-db` | `data/monitoring.db` (or alongside `--db`) | Path to the isolated monitoring SQLite database |
| `--delay` | `2.0` | Delay in seconds between requests |
| `--category` | `laptops` | OLX category to scrape (keys in `scraper/config.py` `CATEGORIES`) |

### Web Reporting UI

- **Listings (`/`):** Defaults to laptops first discovered today (`Asia/Karachi`), with toggles for *Seen today* and *All listings*, keyword search across title/description, city filter, PKR min/max price filter, discovery date range, sorting, and OLX links.
- **Performance (`/performance`):** Shows request counts, Average latency, P50, P95, **P99 (slowest 1%)**, **P99.9 (slowest 0.1%)**, attempt/final failure rates, retries, and run history (including crashed/incomplete runs).
- Reads `olx.db` and `monitoring.db` strictly read-only (`?mode=ro` + `PRAGMA query_only = ON`). See [TECH_DEBT.md](TECH_DEBT.md) `[DEBT-003]` for the intentional unauthenticated private-LAN/Tailscale HTTP compromise.

## Production (Docker on Ubuntu mini PC)

The production deploy is a Docker container scheduled by systemd. See
[`deploy/README.md`](deploy/README.md) for the full one-time setup and
day-to-day operations guide.

The short version:

```bash
# One-time, on the box
sudo docker login ghcr.io            # PAT with read:packages
sudo docker volume create laptop-tracker-data
sudo cp deploy/systemd/olx-scraper.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now olx-scraper.timer

# Trigger a scrape right now (or wait for the 09:00 / 21:00 timer)
sudo systemctl start olx-scraper.service
sudo journalctl -u olx-scraper.service -f
```

## CI/CD

Every push to `main` and every `v*` tag triggers the `Release` workflow
(`.github/workflows/release.yml`):

1. Run `pytest` — if tests fail, the workflow stops here. **No image is published.**
2. Log in to `ghcr.io` using the workflow's automatic `GITHUB_TOKEN`.
3. Compute image tags (`:latest` rolling, `:sha-<short>` immutable, `:v1.0.0` for tagged releases).
4. Build the image and push to `ghcr.io/fe4rlesscloak/laptop-tracker`.

The Ubuntu box uses `--pull=always` in its systemd service, so a new release
goes live on the next scheduled run. No SSH, no manual deploy.

**Rollback:** edit `olx-scraper.service` to pin the image tag (e.g. `:v1.0.0`
or `:sha-abc1234`), then `sudo systemctl daemon-reload && sudo systemctl
start olx-scraper.service`. Full procedure in `deploy/README.md`.

## Output

- **SQLite database** at `data/olx.db` (default locally) or
  `/app/data/olx.db` in the container — the source of truth.
- **Exports** written to `data/listings-YYYY-MM-DD.csv` and/or
  `data/listings-YYYY-MM-DD.json`. The date label is the **scrape date**,
  not the listing date, so each run writes a fresh pair of files.

Each listing stores: `item_id`, `title`, `price`, `price_numeric`, `currency`,
`location`, `city`, `relative_time`, `posted_at`, `description`, `image_urls`,
`item_url`, `is_featured`, `scraped_at`, `seller_name`.

The `seller_name` field is captured from the OLX item page (JSON-LD
structured data, with a visible-DOM fallback). See `TECH_DEBT.md` [DEBT-001]
for the known-fragility note on this selector.

## Tests

```bash
uv run --extra dev pytest
```

The test suite covers the storage layer, HTML parsers, fetcher + attempt telemetry, runner + monitoring integration, isolated monitoring model, and read-only Web UI.

## Project structure

```
scraper/
  config.py     Central configuration (cities, time window, delay, URLs)
  storage.py    SQLite schema, upsert logic, CSV/JSON export
  monitoring.py Isolated monitoring DB, archive import, latency & run telemetry
  web.py        Read-only FastAPI Web UI (listings search + performance stats)
  fetcher.py    Polite HTTP client (User-Agent, delay, retry/backoff, telemetry)
  parsers.py    HTML parsing, price normalization, relative-time parsing, seller name
  runner.py     Orchestrates fetch → filter → enrich → upsert → monitoring → export
  cli.py        Command-line entry point
tests/          Unit + integration tests
SPECS.md        Active specification
TECH_DEBT.md    Intentional compromises (seller selector, tz fallback, no-auth LAN UI)
Dockerfile      Image build for the release artifact
docker-compose.yml  Web UI service + manual scraper runner sharing laptop-tracker-data
.github/workflows/release.yml  CI/CD: tests → build → push to ghcr.io
deploy/         Ubuntu mini PC systemd unit files + setup guide
```

## Roadmap (future work)

- A "flag lucrative deals" analysis system (no ML). The `seller_name` field
  shipped in Release 1.0.0 supports this — repeated sellers at consistently
  low prices are a stronger signal than one-off listings.
