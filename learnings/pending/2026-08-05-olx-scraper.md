# Learning Record

## Record Type

- **QUIRK** — non-obvious repository behavior or edge case future sessions may repeat.

---

## Metadata

- **Date Recorded:** 2026-08-05
- **Affected Subsystem:** OLX Pakistan HTML parsing
- **Related Files:** `scraper/parsers.py`, `scraper/config.py`
- **Related Spec:** `SPECS.md`

---

## Symptom / Context

During implementation of the OLX Pakistan laptop scraper, the item-detail parser
initially returned empty descriptions for every listing even though the item
pages were fetched successfully (image URLs were captured). The commonly-cited
selector `[data-aut-id="itemDescriptionContent"]` matched nothing on the live
site.

Also, the time-window filter (`is_within_hours`) failed a boundary test: a
listing posted "1 day ago" was dropped when the window was exactly 24 hours,
because a few microseconds of wall-clock time elapsed between parsing the
relative time and comparing it, pushing the age marginally over 24h.

## Root Cause

1. OLX Pakistan's description lives in `<div aria-label="Description">` with the
   actual text in an inner `<span>` (class `_7a99ad24`). The
   `data-aut-id="itemDescriptionContent"` attribute used by many tutorials does
   not exist on this site. The outer div also contains a "Description" heading,
   so `get_text` on the container includes the heading unless the inner span is
   selected.
2. Relative-time strings are approximate ("1 day ago" may be 24-48h), and the
   comparison `now - posted <= timedelta(hours=24)` is fragile at the exact
   boundary due to timing drift.

## Prevention Rule

- For OLX Pakistan item pages, extract the description from the inner content
  element of `[aria-label="Description"]` (prefer `._7a99ad24` or the first
  `<span>`), not from a `data-aut-id` attribute.
- When filtering by a relative-time window, add a small tolerance (e.g., 5
  minutes) so listings right at the boundary are kept, matching the intent to
  capture fresh listings.

## Blueprint

```python
# scraper/parsers.py
_BOUNDARY_TOLERANCE = timedelta(minutes=5)

def is_within_hours(relative, hours):
    posted = parse_relative_time(relative)
    if posted is None:
        return True  # fail open
    age = datetime.now(timezone.utc) - posted
    return age <= timedelta(hours=hours) + _BOUNDARY_TOLERANCE

def _find_description(soup):
    container = soup.select_one('[aria-label="Description"]')
    if container:
        inner = container.select_one("._7a99ad24") or container.find("span")
        if inner:
            text = inner.get_text(" ", strip=True)
            if text:
                return text
    return None
```

## Verification

- `uv run --extra dev pytest` passes (27 tests).
- Live run: `uv run python -m scraper --hours 24 --export csv json` populates
  `data/olx.db` with listings that include non-empty descriptions.

---

## Evolution Candidates

### Candidate 1

- **Destination:** `SKILL`
- **Priority:** Medium
- **Status:** PENDING
- **Suggested Target:** a new domain skill, e.g. `.agents/skills/olx-scraping.md`

#### Suggestion

Create a domain skill documenting OLX Pakistan's HTML structure for future
scraping work: search-result card fields, the `aria-label="Description"`
description container, price notation ("Lac"/"Lacs"/"Crore"), relative-time
strings, and the city/category URL scheme.

#### Rationale

This is reusable, site-specific knowledge that future sessions (e.g., extending
the scraper, adding the deal-flagging system, or scraping other categories)
will need. Encoding it as a skill prevents re-discovering the HTML structure
each time.

### Candidate 2

- **Destination:** `AGENTS`
- **Priority:** Low
- **Status:** PENDING
- **Suggested Target:** `AGENTS.md` §1 Project Snapshot

#### Suggestion

Update the build/test commands in `AGENTS.md` to reflect that the developer
prefers **UV** as the package manager: build `uv sync`, test
`uv run --extra dev pytest`, run `uv run python -m scraper`.

#### Rationale

The developer explicitly requested UV over venv/pip during this session. The
current AGENTS.md snapshot lists `pip install -r requirements.txt` and
`python -m pytest`, which are not how this project is actually run.
