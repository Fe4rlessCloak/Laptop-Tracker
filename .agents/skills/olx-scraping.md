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
- Category path uses a slug + category ID, e.g. the Laptops category:
  `laptops_c708203`. **Use the dedicated Laptops category** (`laptops_c708203`),
  not the broader "Computers & Accessories" category
  (`laptops-computers-accessories_c443`); the broader category mixes laptops
  with RAM, GPUs, SSDs, mice, chargers, tablets, and other accessories.
  Verify by fetching the candidate category URL and inspecting the first page
  of results before introducing keyword filters.
- City path uses a slug + geographic region ID, e.g.:
  `islamabad_g4060615`, `rawalpindi_g4060681`
- Full search URL:
  `https://www.olx.com.pk/{city}_{gid}/{category}_{cid}/q-{query}`
- **Sorting:** append `sorting=desc-creation` to request newest-first ordering.
  OLX's default sort surfaces old featured/relevance ads at the top, so without
  this parameter the scraper captures nothing within the window.
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
- Do **not** early-stop on a duplicate listing. Featured ads break OLX's
  newest-first ordering, so a duplicate on an early page does not guarantee
  newer ads are absent from later pages. Rely on time-window exhaustion and
  `MAX_PAGES` instead.
- Do not add a `--no-early-stop` flag; there is no duplicate early-stop to
  disable.

---

## Blueprint

```python
# scraper/config.py
SORT_PARAM = "sorting=desc-creation"
CATEGORIES = {"laptops": "laptops_c708203"}

# scraper/runner.py — pagination (no duplicate early-stop)
def build_search_url(city_slug: str, page: int, category: str = "laptops") -> str:
    path = config.CATEGORIES[category]
    base = (
        f"{config.BASE_URL}/{city_slug}/"
        f"{path}/{config.SEARCH_QUERY}"
    )
    return f"{base}?page={page}&{config.SORT_PARAM}"

# Stop paging only on time-window exhaustion or the MAX_PAGES cap.
for page in range(1, config.MAX_PAGES + 1):
    html = fetcher.get(build_search_url(city_slug, page))
    listings = parse_search_results(html, city)
    fresh = [l for l in listings if is_within_hours(l["relative_time"], hours)]
    if not fresh:
        break  # time-window exhausted
    for listing in fresh:
        # ... fetch detail, upsert (no listing_exists early-stop)
```

---

## Verification

Before considering OLX scraping work complete:

- [ ] Search-page fields (title, price, location, relative time) parse correctly.
- [ ] Item-page description extracts from the inner span of `[aria-label="Description"]`.
- [ ] Search URLs include `sorting=desc-creation` for newest-first ordering.
- [ ] Pagination captures multiple pages and stops on time-window exhaustion or the `MAX_PAGES` cap (no duplicate early-stop).
- [ ] Existing tests pass (`uv run --extra dev pytest`).
