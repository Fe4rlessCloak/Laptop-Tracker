"""Polite HTTP fetching for the OLX scraper.

Wraps ``requests`` with a realistic browser User-Agent, a configurable delay
between requests, and retry/backoff on transient failures. Keeping all network
behaviour in one place makes it easy to swap in a headless browser later if OLX
starts blocking plain HTTP requests.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from scraper.config import (
    MAX_RETRIES,
    RETRY_BACKOFF,
    USER_AGENT,
)

# HTTP status codes considered transient and worth retrying.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """Raised when a page cannot be fetched after retries."""


class Fetcher:
    """A small HTTP client that fetches pages politely."""

    def __init__(
        self,
        delay: float = 2.0,
        max_retries: int = MAX_RETRIES,
        backoff: float = RETRY_BACKOFF,
        user_agent: str = USER_AGENT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.delay = delay
        self.max_retries = max_retries
        self.backoff = backoff
        self.user_agent = user_agent
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def get(self, url: str) -> str:
        """Fetch ``url`` and return its text, retrying transient failures.

        A short delay is applied before each request to stay polite to the
        target site.
        """
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            if attempt > 1:
                time.sleep(self.backoff * attempt)
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in _TRANSIENT_STATUS:
                    last_error = FetchError(
                        f"Transient status {resp.status_code} for {url}"
                    )
                    continue
                raise FetchError(
                    f"Non-retryable status {resp.status_code} for {url}"
                )
            except requests.RequestException as exc:  # network-level failure
                last_error = exc
        raise FetchError(f"Failed to fetch {url} after retries: {last_error}")

    def sleep_between(self) -> None:
        """Pause between requests to respect the site's rate limits."""
        if self.delay > 0:
            time.sleep(self.delay)
