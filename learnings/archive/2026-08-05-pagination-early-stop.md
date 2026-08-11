# Learning Record

## Record Type

- **QUIRK** — non-obvious repository behavior or edge case future sessions may repeat.

---

## Metadata

- **Date Recorded:** 2026-08-05
- **Affected Subsystem:** OLX scraper pagination / runner
- **Related Files:** `scraper/runner.py`, `scraper/storage.py`, `tests/test_runner.py`
- **Related Spec:** `SPECS.md` (OLX Pagination & Fresh-Listing Capture)

---

## Symptom / Context

The pagination loop originally used a **duplicate early-stop**: stop paging as
soon as a listing already in the database is encountered, on the assumption that
OLX orders results strictly newest-first (so everything older is already known).
Live testing revealed this assumption is **false** and the early-stop caused
fresh listings to be missed.

## Root Cause

OLX pushes **featured** ads to the top of each search page out of chronological
order. This scrambles where normal ads land across pages, so the ordering is NOT
strictly newest-first. A live simulation showed a duplicate on page 2 triggering
the early-stop while page 3 still contained 15 brand-new ads (0–1 minutes old)
that were never reached. The duplicate early-stop was therefore **removed**.

## Prevention Rule

- **Do NOT early-stop on a duplicate listing.** Featured ads break OLX's
  newest-first ordering, so a duplicate on an early page does not guarantee that
  newer ads are absent from later pages.
- Rely on the two safe stopping mechanisms instead:
  1. **Time-window exhaustion** — stop when a page has no listings within the
     window (this is reliable).
  2. **`config.MAX_PAGES` (20)** — safety cap bounding the loop.
- A repeat run now re-fetches and *updates* already-stored listings (upsert),
  so `summary.updated` can be non-zero again.

## Blueprint

```python
# scraper/runner.py — per-city pagination (no duplicate early-stop)
for page in range(1, config.MAX_PAGES + 1):
    html = fetcher.get(build_search_url(city_slug, page))
    listings = parse_search_results(html, city)
    kept = [l for l in listings if is_within_hours(l["relative_time"], hours)]
    if not kept:
        break  # time-window exhausted
    for listing in kept:
        # ... fetch detail, upsert (no listing_exists early-stop)
```

## Verification

- `uv run --extra dev pytest` passes (29 tests).
- `tests/test_runner.py::test_run_does_not_early_stop_on_duplicate` verifies a
  duplicate on page 1 does not prevent capturing a new listing on page 2.

---

## Additional Finding: OLX default sort surfaces old ads

### Symptom / Context

A live run with the new pagination returned **0 fetched / 49 skipped** for a
24h window, even though listings had been captured ~12h earlier. The parser
worked correctly — it extracted relative times like "6 days ago" and
"1 week ago" — but every listing was older than the window, so the time filter
dropped them all.

### Root Cause

OLX's **default search sort is not newest-first**. It surfaces old
featured/relevance ads at the top. The search URL lacked a sort parameter, so
the first page contained only stale ads. Adding `sorting=desc-creation` to the
URL requests newest-first ordering; a live test then returned 15 fresh (24h)
listings on page 1 instead of 0.

### Prevention Rule

- Always append `sorting=desc-creation` to OLX search URLs to get newest-first
  ordering for normal (non-featured) ads.
- Even with the sort, OLX pushes **featured** ads to the top, breaking the
  ordering somewhat. The time-window filter remains the primary gate; do not
  rely on sort order alone.

### Blueprint

```python
# scraper/config.py
SORT_PARAM = "sorting=desc-creation"

# scraper/runner.py
def build_search_url(city_slug: str, page: int = 1) -> str:
    base = (
        f"{config.BASE_URL}/{city_slug}/"
        f"{config.LAPTOPS_CATEGORY_PATH}/{config.SEARCH_QUERY}"
    )
    return f"{base}?page={page}&{config.SORT_PARAM}"
```

### Verification

- Live run: `uv run python -m scraper --cities islamabad rawalpindi --hours 24`
  now reports `Fetched 109 listings, 75 new` (previously 0 fetched).
- `uv run --extra dev pytest` passes (29 tests).

---

## Evolution Candidates

### Candidate 1

- **Destination:** `SKILL`
- **Priority:** Medium
- **Status:** ACCEPTED
- **Suggested Target:** `.agents/skills/olx-scraping.md`

#### Suggestion

Add a note to the OLX scraping domain skill that the pagination loop must **not**
early-stop on a duplicate listing. Featured ads break OLX's newest-first
ordering, so a duplicate on an early page does not guarantee newer ads are
absent from later pages. Rely on time-window exhaustion and `MAX_PAGES` instead.

#### Rationale

This is reusable, non-obvious behavior. A future session might reintroduce the
duplicate early-stop as an "optimization" and silently miss fresh listings.
Documenting the pitfall prevents regression.

### Candidate 2

- **Destination:** `SPECS`
- **Priority:** High
- **Status:** ACCEPTED
- **Suggested Target:** `SPECS.md` (OLX Pagination & Fresh-Listing Capture, Unit 2)

#### Suggestion

Update Unit 2 of the pagination spec to require appending `sorting=desc-creation`
to the search URL so OLX returns newest-first ordering. Without it, the default
sort surfaces only old featured/relevance ads and the scraper captures nothing
within the window.

#### Rationale

The spec described pagination but omitted the sort parameter, which is required
for correctness. Without reconciling the spec, a future session could repeat the
"0 fetched" failure.

### Candidate 3

- **Destination:** `SKILL`
- **Priority:** High
- **Status:** ACCEPTED
- **Suggested Target:** `.agents/skills/olx-scraping.md`

#### Suggestion

Document in the OLX scraping domain skill that search URLs must include
`sorting=desc-creation` for newest-first ordering, and that featured ads still
break the ordering so the time-window filter is the primary gate.

#### Rationale

This is critical, reusable site-specific knowledge. The URL scheme section of
the skill currently omits the sort parameter, which would cause future scraping
work to repeat the "0 fetched" failure.

### Candidate 4

- **Destination:** `SPECS`
- **Priority:** High
- **Status:** ACCEPTED
- **Suggested Target:** `SPECS.md` (OLX Pagination & Fresh-Listing Capture, Unit 3)

#### Suggestion

Update Unit 3 of the pagination spec to remove the duplicate early-stop. The
spec currently instructs the runner to "stop at the first already-known one",
but featured ads break OLX's newest-first ordering, so this causes fresh
listings on later pages to be missed. The runner should stop only on
time-window exhaustion or the `MAX_PAGES` cap.

#### Rationale

The spec's literal instruction (duplicate early-stop) was implemented and then
reverted because it was incorrect. The spec must be reconciled so the next
session does not re-implement the buggy behavior.
