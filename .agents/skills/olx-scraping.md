# Domain Skill: OLX Pakistan Scraping

## Purpose

Apply these rules whenever modifying or extending the OLX Pakistan scraper
(`scraper/`). This skill captures the site's HTML structure and URL scheme so
future work (extending the scraper, adding the deal-flagging system, scraping
other categories) does not re-discover them.

---

## Domain Principles

- OLX Pakistan is server-rendered: listing data is present in the HTML, so a
  plain-HTTP fetcher (`requests` + `beautifulsoup4`) suffices. No headless
  browser is required.
- Prefer reading data from the **search-result page** (title, price, location,
  relative time, featured badge) without visiting each item's link. Only fetch
  the item page when the full description / image URLs are needed.
- Stay polite: configurable delay between requests, no aggressive parallelism,
  no image downloads (capture URLs as text only).

---

## URL Scheme

- Base: `https://www.olx.com.pk`
- Category path uses a slug + category ID, e.g. laptops:
  `laptops-computers-accessories_c443`
- City path uses a slug + geographic region ID, e.g.:
  `islamabad_g4060615`, `rawalpindi_g4060681`
- Full search URL:
  `https://www.olx.com.pk/{city}_{gid}/{category}_{cid}/q-{query}`
- **Pagination:** append `?page=N` (e.g. `?page=2`). OLX updates `?page=N` as
  you scroll. Real-world depth for a 24h window: Rawalpindi ≈ 5 pages,
  Islamabad ≈ 11 pages.

---

## Required Patterns

- Extract the numeric item ID from an item URL with the `-iid-(\d+)` pattern
  (see `_extract_item_id` in `scraper/parsers.py`).
- Read the relative time ("2 hours ago", "7 days ago") from each search card
  and use it to filter by the time window **before** fetching item pages.
- Normalize Pakistani price notation: "Lac"/"Lacs"/"Lakh"/"Lakhs" = 100_000,
  "Crore"/"Crores" = 10_000_000 (see `normalize_price` in `scraper/parsers.py`).
- Detect the Featured badge from the card text (see `_parse_card` in
  `scraper/parsers.py`). Note: featured status is informational only — the
  time-window filter is the primary gate for keeping the DB clean of stale ads.

---

## Item Detail Page

- The description lives in `<div aria-label="Description">`; the actual text is
  in an inner `<span>` (class `_7a99ad24`). The outer div also contains a
  "Description" heading, so select the inner span, not the container.
- The `data-aut-id="itemDescriptionContent"` attribute used by many tutorials
  does **not** exist on OLX Pakistan — do not rely on it.
- See `_find_description` in `scraper/parsers.py`.

---

## Avoid

- Do not rely on `data-aut-id` attributes for OLX Pakistan content.
- Do not use a headless browser for pagination — `?page=N` works with plain
  HTTP.
- Do not fetch item pages just to determine an ad's age; the search card
  already carries the relative time.
- Do not add a `--no-early-stop` flag; early-stop on duplicate is always on.

---

## Blueprint

```python
# scraper/runner.py — pagination with early-stop
def build_search_url(city_slug: str, page: int) -> str:
    base = (
        f"{config.BASE_URL}/{city_slug}/"
        f"{config.LAPTOPS_CATEGORY_PATH}/{config.SEARCH_QUERY}"
    )
    return f"{base}?page={page}"

# Stop paging when a page has no fresh listings OR we hit an already-stored ID.
for page in range(1, config.MAX_PAGES + 1):
    html = fetcher.get(build_search_url(city_slug, page))
    listings = parse_search_results(html, city)
    fresh = [l for l in listings if is_within_hours(l["relative_time"], hours)]
    if not fresh:
        break  # time-window exhausted
    for listing in fresh:
        if storage.listing_exists(conn, listing["item_id"]):
            return  # duplicate early-stop: everything older is already known
        # ... fetch detail, upsert
```

---

## Verification

Before considering OLX scraping work complete:

- [ ] Search-page fields (title, price, location, relative time) parse correctly.
- [ ] Item-page description extracts from the inner span of `[aria-label="Description"]`.
- [ ] Pagination captures multiple pages and stops on time-window exhaustion or duplicate.
- [ ] Existing tests pass (`uv run --extra dev pytest`).
