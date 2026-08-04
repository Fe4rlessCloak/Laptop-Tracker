"""HTML parsing for OLX Pakistan search results and item detail pages.

The site is server-rendered, so listing data is present in the HTML. This module
extracts structured listings from that HTML, normalizes prices (which use
Pakistani notation such as "Lac"/"Lacs" and "Crore"), and converts relative
time strings ("1 day ago") into approximate ages for time-window filtering.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Price normalization
# ---------------------------------------------------------------------------

# Pakistani number words and their multipliers.
_NUMBER_WORDS = {
    "thousand": 1_000,
    "lac": 100_000,
    "lacs": 100_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
}

_PRICE_RE = re.compile(
    r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<word>thousand|lacs?|lakhs?|crores?)?",
    re.IGNORECASE,
)


def normalize_price(raw: Optional[str]) -> Optional[float]:
    """Convert an OLX price string into a numeric value, or None if unparseable.

    Handles plain numbers ("Rs 39,000" -> 39000) and Pakistani notation
    ("Rs 1.40 Lac" -> 140000, "Rs 10.40 Lacs" -> 1040000, "Rs 1.5 Crore" -> 15000000).
    """
    if not raw:
        return None
    text = raw.replace(",", "").strip()
    match = _PRICE_RE.search(text)
    if not match:
        return None
    try:
        amount = float(match.group("amount"))
    except ValueError:
        return None
    word = (match.group("word") or "").lower()
    multiplier = _NUMBER_WORDS.get(word, 1)
    return amount * multiplier


# ---------------------------------------------------------------------------
# Relative time parsing
# ---------------------------------------------------------------------------

_RELATIVE_RE = re.compile(
    r"(?P<num>\d+)\s*(?P<unit>minute|hour|day|week|month|year)s?\s*ago",
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,  # ~30 days
    "year": 31536000,  # ~365 days
}


def parse_relative_time(relative: Optional[str]) -> Optional[datetime]:
    """Convert a relative time string ("2 days ago") into an approximate UTC datetime.

    Returns None if the string cannot be parsed.
    """
    if not relative:
        return None
    match = _RELATIVE_RE.search(relative)
    if not match:
        return None
    num = int(match.group("num"))
    unit = match.group("unit").lower()
    seconds = num * _UNIT_SECONDS[unit]
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


# Small tolerance (minutes) so listings right at the window boundary are kept.
# Relative-time strings are approximate ("1 day ago" may be 24-48h), and a tiny
# amount of wall-clock time elapses between parsing and comparison, so a strict
# <= comparison can drop a listing that is effectively within the window.
_BOUNDARY_TOLERANCE = timedelta(minutes=5)


def is_within_hours(relative: Optional[str], hours: int) -> bool:
    """Return True if the relative time string is within ``hours`` of now."""
    posted = parse_relative_time(relative)
    if posted is None:
        # If we cannot determine the age, keep the listing (fail open) so we
        # do not silently drop data.
        return True
    age = datetime.now(timezone.utc) - posted
    return age <= timedelta(hours=hours) + _BOUNDARY_TOLERANCE


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------

_ITEM_ID_RE = re.compile(r"-iid-(\d+)")


def _extract_item_id(url: str) -> Optional[str]:
    """Extract the numeric OLX item ID from an item URL."""
    match = _ITEM_ID_RE.search(url)
    return match.group(1) if match else None


def parse_search_results(html: str, city: str) -> List[Dict[str, Any]]:
    """Parse listing cards from a search-results page.

    Returns a list of partial listings (no description yet; that comes from the
    item detail page). Each entry carries enough to identify, filter, and later
    enrich the listing.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings: List[Dict[str, Any]] = []

    # OLX renders each listing as an <li> containing an <a href="/item/...">.
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/item/" not in href:
            continue
        item_id = _extract_item_id(href)
        if item_id is None:
            continue

        # Skip if we already captured this item (a card may contain multiple
        # anchors pointing at the same listing).
        if any(l["item_id"] == item_id for l in listings):
            continue

        card = link.find_parent("li") or link
        listing = _parse_card(card, href, item_id, city)
        if listing is not None:
            listings.append(listing)

    return listings


def _parse_card(card, href: str, item_id: str, city: str) -> Optional[Dict[str, Any]]:
    """Extract fields from a single listing card element."""
    title_el = card.find("h6") or card.find("h2") or card.find("a", href=True)
    title = title_el.get_text(strip=True) if title_el else None
    if not title:
        return None

    text = card.get_text(" ", strip=True)

    price = _find_price(card, text)
    location = _find_location(text)
    relative = _find_relative_time(text)
    is_featured = bool(card.find(string=re.compile(r"Featured", re.IGNORECASE)))

    image_url = None
    img = card.find("img")
    if img and img.get("src"):
        image_url = img["src"]

    return {
        "item_id": item_id,
        "title": title,
        "price": price,
        "price_numeric": normalize_price(price),
        "currency": "PKR" if price else None,
        "location": location,
        "city": city,
        "relative_time": relative,
        "posted_at": parse_relative_time(relative).isoformat()
        if parse_relative_time(relative)
        else None,
        "description": None,
        "image_urls": [image_url] if image_url else [],
        "item_url": href if href.startswith("http") else f"https://www.olx.com.pk{href}",
        "is_featured": is_featured,
    }


def _find_price(card, text: str) -> Optional[str]:
    """Locate the price string (e.g. 'Rs 39,000' or 'Rs 1.40 Lac')."""
    # Prefer an element whose text starts with "Rs".
    for el in card.find_all(string=re.compile(r"^\s*Rs\b", re.IGNORECASE)):
        candidate = el.strip()
        if candidate:
            return candidate
    # Fall back to scanning the card text.
    match = re.search(r"Rs\s+[\d.,]+\s*(?:thousand|lacs?|lakhs?|crores?)?", text, re.IGNORECASE)
    return match.group(0) if match else None


def _find_location(text: str) -> Optional[str]:
    """Extract the location segment from the card text.

    The card text is a flattened string; the location typically appears after
    the title and before the relative time. We take the segment between the
    title and the relative-time marker as a best-effort location.
    """
    match = re.search(r"\bago\b", text)
    if not match:
        return None
    # Take up to ~60 chars before "ago" as the location, then trim.
    before = text[: match.start()].strip()
    # The location is usually the last comma-separated part before "ago".
    parts = [p.strip() for p in before.split(",") if p.strip()]
    return parts[-1] if parts else None


def _find_relative_time(text: str) -> Optional[str]:
    """Extract the relative time string (e.g. '1 day ago')."""
    match = _RELATIVE_RE.search(text)
    return match.group(0) if match else None


# ---------------------------------------------------------------------------
# Item detail parsing
# ---------------------------------------------------------------------------

def parse_item_detail(html: str, listing: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a listing with the full description and image URLs from its page.

    Only text is captured; image files are never downloaded.
    """
    soup = BeautifulSoup(html, "html.parser")

    description = _find_description(soup)
    if description:
        listing["description"] = description

    image_urls = _find_image_urls(soup)
    if image_urls:
        listing["image_urls"] = image_urls

    return listing


def _find_description(soup: BeautifulSoup) -> Optional[str]:
    """Best-effort extraction of the item description text.

    OLX wraps the description in a ``<div aria-label="Description">`` whose
    inner ``<span>`` holds the actual text (the outer div also contains a
    "Description" heading we must exclude). We try several selectors in order
    of confidence, falling back to any element whose class contains
    "description".
    """
    # Prefer the inner content element of the aria-labelled description block.
    container = soup.select_one('[aria-label="Description"]')
    if container:
        inner = container.select_one("._7a99ad24") or container.find("span")
        if inner:
            text = inner.get_text(" ", strip=True)
            if text:
                return text

    for selector in (
        '[data-aut-id="itemDescriptionContent"]',
        ".descriptioncontent",
        "[class*='description']",
    ):
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return None


def _find_image_urls(soup: BeautifulSoup) -> List[str]:
    """Collect image URLs from the item page (text only, no download)."""
    urls: List[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http") and src not in urls:
            urls.append(src)
    return urls
