# Learning Record

## Record Type

- **PATTERN** — a reusable, better way discovered during implementation.

---

## Metadata

- **Date Recorded:** 2026-08-29
- **Affected Subsystem:** OLX scraper URL builder / config
- **Related Files:** `scraper/config.py`, `scraper/runner.py`, `scraper/cli.py`, `.agents/skills/olx-scraping.md`
- **Related Spec:** `SPECS.md` (Switch OLX search base to the Laptops-only category)

---

## Symptom / Context

GitHub Issue #1 proposed adding **configurable exclusion filters** (negative
keywords like `-ram`, `-ssd`, `-gpu`, `-tablet`) to the OLX search URL so the
scraper would stop ingesting non-laptop items from the "Computers & Accessories"
category. The Issue was filed with the assumption that the broader category
was the only available source.

A live `web_fetch` of OLX's URL hierarchy revealed the assumption was wrong:
OLX also exposes a **dedicated Laptops category** (`laptops_c708203`) that
returns 100% laptop listings with no filtering machinery required.
City-scoped variants (`islamabad_g4060615/laptops_c708203/q-laptop` and
`rawalpindi_g4060681/laptops_c708203/q-laptop`) work identically and preserve
the runner's per-city URL scheme.

The keyword-filter approach would have added:
- a new `EXCLUDED_KEYWORDS` config list with hardcoded maintenance
- post-fetch URL serialization logic for negative-keyword syntax
- ongoing drift as OLX adds new non-laptop subcategories

…all to solve a problem that OLX's own category hierarchy already solved at
the source.

## Root Cause

The Issue was filed before anyone verified OLX's **category hierarchy**. A
two-minute `web_fetch` of candidate category URLs (instead of jumping to
keyword filtering) would have surfaced `laptops_c708203` and made the
exclusion-filter design unnecessary.

## Prevention Rule

**Before proposing keyword filters or other post-fetch filtering, verify the
upstream category hierarchy.** When a site exposes multiple sub-categories
(OLX does — Laptops, Computers & Accessories, Mobile Phones, Tablets, etc.),
the narrower sub-category is almost always a better fix than negative
keyword matching: it is maintained by the site, returns only the desired
listings, and removes maintenance burden from the scraper.

Concretely: when an Issue or feature request involves "filter out X from
results," first fetch the candidate narrower-category URL and inspect the
first page of results. If the narrower category already excludes X, prefer
it over keyword filters.

## Blueprint

```python
# scraper/config.py — extensible category dict (keyed by short slug)
CATEGORIES = {
    "laptops": "laptops_c708203",  # dedicated Laptops category, laptop-only
}

# scraper/runner.py — build_search_url reads from the dict
def build_search_url(city_slug: str, page: int = 1, category: str = "laptops") -> str:
    path = config.CATEGORIES[category]   # raises KeyError on unknown category
    base = f"{config.BASE_URL}/{city_slug}/{path}/{config.SEARCH_QUERY}"
    return f"{base}?page={page}&{config.SORT_PARAM}"
```

## Verification

- `uv run --extra dev pytest -q` — 32/32 pass (29 existing + 3 new URL-shape tests)
- `web_fetch https://www.olx.com.pk/islamabad_g4060615/laptops_c708203?q-laptop`
  — first 20 listings are all laptops (MacBook, Dell, HP, ThinkPad, MSI, etc.);
  no RAM, SSDs, GPUs, mice, chargers, tablets, or iPads
- `python -m scraper --help` — `--category` flag present with default `laptops`
- GitHub Issue #1 closed with a comment explaining the category switch

---

## Evolution Candidates

### Candidate 1

- **Destination:** `SKILL`
- **Priority:** Medium
- **Status:** ACCEPTED
- **Suggested Target:** `.agents/skills/olx-scraping.md` "URL Scheme" section

#### Suggestion

The skill's URL Scheme section should explicitly remind Evolution sessions
to **verify the upstream category hierarchy** (via a live `web_fetch` of the
candidate category URL) before proposing negative-keyword filters or other
post-fetch filtering machinery. The current section already documents the
`laptops_c708203` vs `laptops-computers-accessories_c443` distinction; add a
short paragraph framing it as the general rule, not a one-off observation.

#### Rationale

This is a reusable, repository-independent lesson: any future Evolution
session that touches an OLX scraping Issue (or a similar Issue on another
classifieds site with a category hierarchy) is at risk of repeating the
same design detour. A single short paragraph in the skill prevents the
recurrence. This complements the existing "Avoid" guidance and the
Blueprint example.
