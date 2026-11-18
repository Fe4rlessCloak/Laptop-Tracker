# Learning Record

## Record Type

**QUIRK**

---

## Metadata

- **Date Recorded:** 2026-11-18
- **Affected Subsystem:** HTTP fetching (`scraper/fetcher.py`, `scraper/config.py`)
- **Related Files:** `scraper/config.py::BROWSER_HEADERS`, `scraper/fetcher.py::Fetcher.__init__`
- **Related Spec:** none (unplanned operational fix)

---

## Symptom / Context

Every scheduled run since 2026-10-25 recorded `completed-with-fetch-errors` and stored no new listings. Live requests returned:

```text
GET  1.20s  503  https://www.olx.com.pk/islamabad_g4060615/laptops_c708203/q-laptop?page=1&sorting=desc-creation
```

The response body title was `Security check | OLX` with `retry-after: 3600`. All three retries per city failed within ~6 seconds, so both cities failed on every run. The CLI still exited `0`, so systemd reported the unit as successful and the failure went unnoticed for weeks.

## Root Cause

OLX's edge blocks a request that **claims** to be Chrome via `User-Agent` but does not send the headers a real Chrome document navigation sends. The discriminator is header coherence, not the TLS fingerprint.

Measured on 2026-11-18 against the live city search URL, using the same Python `requests` client for every row (so TLS stack held constant):

| Headers sent | Status |
|---|---|
| `requests` default UA | 200 |
| Chrome `User-Agent` only (previous code) | **503** |
| Chrome `User-Agent` + `Accept` + `Accept-Language` + `Sec-Fetch-{Dest,Mode,Site}` | **200** |

Header subsets were also tested individually. `UA+Accept`, `UA+Accept-Language`, and `UA+Sec-Fetch-*` each still returned 503; only the complete group returned 200. `Sec-Fetch-User`, `Upgrade-Insecure-Requests`, and `sec-ch-ua*` are not required. The result was deterministic across repeated runs and held for item detail pages, both cities, and pagination pages 1–3, with the existing parsers reading 24 listings per page.

A concurrent diagnosis from another agent concluded the cause was Chrome's TLS/JA3 fingerprint and recommended replacing `requests` with `curl_cffi` impersonation. That recommendation was unnecessary and its stated evidence was inconsistent with its own mechanism (its table showed the default `requests` UA — identical TLS fingerprint — returning 200). Do not add `curl_cffi` unless header coherence stops working.

## Prevention Rule

When OLX starts returning `503` with `Security check | OLX`, reproduce it against the live URL first and compare header sets before changing the HTTP client. Keep `scraper.config.BROWSER_HEADERS` as a complete Chrome document-navigation header set; never reduce it to a bare `User-Agent`.

## Blueprint

```python
# scraper/config.py
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

# scraper/fetcher.py
self.session = session or requests.Session()
self.session.headers.update(BROWSER_HEADERS)
self.session.headers.update({"User-Agent": self.user_agent})
```

## Verification

- `uv run --extra dev pytest` passes (91 tests).
- A live `uv run python -m scraper --cities islamabad --hours 48 --db /tmp/x.db --monitoring-db /tmp/mon.db` prints `GET ... 200` for search and item pages, reports `0 errors`, and stores listings.
- An isolated probe of the production `--hours 24` window returns `within24h=15` on page 1 for both cities.

---

## Evolution Candidates

### Candidate 1

- **Destination:** `SKILL`
- **Priority:** High
- **Status:** PENDING
- **Suggested Target:** `.agents/skills/olx-scraping.md`

#### Suggestion

Document the header-coherence rule in the OLX scraping skill: the required `BROWSER_HEADERS` set, the `503 Security check | OLX` + `retry-after: 3600` signature, the verified header-vs-TLS finding, and the instruction to measure live header sets before changing HTTP client libraries.

#### Rationale

The previous guidance only said a plain-HTTP `requests` fetcher "suffices", which is true but does not warn that a bare `User-Agent` is actively blocked. Without this, a future session is likely to misdiagnose the block as a TLS-fingerprint problem and introduce an unnecessary binary dependency.
