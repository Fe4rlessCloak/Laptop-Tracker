# Tech Debt & Compromise Tracker

Record only intentional technical compromises made to satisfy the active specification. Do not record ordinary implementation decisions or future feature ideas.

**Write path:** The **Repository Evolution** skill writes entries to this file. **Implementation** does not write here directly — it proposes a tech-debt entry via a learning file in `learnings/pending/` with an Evolution Candidate whose `Destination: TECH_DEBT`. Implementation may add the `// TECHDEBT: DEBT-001` marker in code, but the entry itself is created by the evolver.

---

## [DEBT-001] – OLX seller-name selector is best-effort against the live item page

- **Date Added:** 2026-08-30
- **Status:** OPEN
- **File Location:** `scraper/parsers.py::_find_seller_name` (// TECHDEBT: DEBT-001)
- **Spec Reference:** `SPECS.md` (Release 1.0.0 — Seller Name, Docker, CI/CD, Ubuntu Deployment)
- **Introduced By:** (to be filled by Implementation session)

### Compromise

The `seller_name` extraction in `scraper/parsers.py::_find_seller_name` targets the seller card on the current OLX Pakistan item page HTML. The selector is designed from a captured fixture and is not contractually guaranteed by OLX. If OLX redesigns the seller card (which they have done before with adjacent elements such as the description block — see learning `2026-08-05-olx-scraper.md`), the selector may go stale and `seller_name` will silently become `NULL` for affected listings.

### Justification

Including seller name in Release 1.0.0 captures useful attribution data for the future "flag lucrative deals" feature (a known repeat seller at a low price is a stronger signal than an unknown seller at the same price). The cost of a best-effort selector is acceptable because the failure mode is graceful: a `NULL` `seller_name` does not break ingestion, the time-window filter, the export, or the CI/CD pipeline. Adding the field now lets us start collecting data even if the selector needs maintenance later.

### Impact

- Reduced data quality for the `seller_name` field (some or all listings may have `NULL` after an OLX redesign)
- Silent failure mode: nothing in the pipeline alerts on a sudden drop in non-NULL `seller_name` counts
- Future implementer must inspect the live OLX item page and update the selector if non-NULL rates drop sharply

### Remediation

- Add a small CI check that counts non-NULL `seller_name` values in a recent scrape and fails the build if the rate drops below a threshold (e.g., 80% over the last 100 listings)
- If OLX redesigns the card, capture a new fixture, update `_find_seller_name`, and add a regression test
- Consider an OLX-API-based seller lookup as a long-term replacement if OLX exposes one

### Verification

- A live or recent-scrape query (`SELECT COUNT(*) FILTER (WHERE seller_name IS NOT NULL) * 1.0 / COUNT(*) FROM listings`) returns ≥ 0.80 against current OLX HTML
- A new unit test covers the current selector's HTML fixture; if the fixture is updated (because OLX changed), the test must be updated in the same commit

### Resolution

- **Resolved By:**
- **Resolved On:**
- **Notes:**
