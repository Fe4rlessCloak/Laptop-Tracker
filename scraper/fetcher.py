"""Polite HTTP fetching for the OLX scraper.

Wraps ``requests`` with a realistic browser User-Agent, a configurable delay
between requests, and retry/backoff on transient failures. Keeping all network
behaviour in one place makes it easy to swap in a headless browser later if OLX
starts blocking plain HTTP requests.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

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
        on_attempt: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.delay = delay
        self.max_retries = max_retries
        self.backoff = backoff
        self.user_agent = user_agent
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.on_attempt = on_attempt
        self._attempt_context: Dict[str, Optional[str]] = {
            "page_type": None,
            "city": None,
        }

    def set_attempt_context(
        self,
        *,
        page_type: Optional[str] = None,
        city: Optional[str] = None,
    ) -> None:
        """Set bounded metadata attached to emitted HTTP attempt telemetry."""
        self._attempt_context["page_type"] = page_type
        self._attempt_context["city"] = city

    def _emit_attempt(
        self,
        *,
        attempt_number: int,
        status_code: Optional[int],
        outcome: str,
        is_final: bool,
        duration_ms: float,
    ) -> None:
        if self.on_attempt is None:
            return
        event = {
            "page_type": self._attempt_context.get("page_type"),
            "city": self._attempt_context.get("city"),
            "attempt_number": attempt_number,
            "status_code": status_code,
            "outcome": outcome,
            "is_final": is_final,
            "duration_ms": duration_ms,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.on_attempt(event)
        except Exception:
            # Telemetry observers must never abort HTTP fetching.
            pass

    def get(self, url: str) -> str:
        """Fetch ``url`` and return its text, retrying transient failures.

        A short delay is applied before each request to stay polite to the
        target site.
        """
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            if attempt > 1:
                time.sleep(self.backoff * attempt)
            t0 = time.perf_counter()
            try:
                resp = self.session.get(url, timeout=30)
                elapsed = time.perf_counter() - t0
                elapsed_ms = elapsed * 1000.0
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] GET  {elapsed:5.2f}s  {resp.status_code}  {url}")
                if resp.status_code == 200:
                    self._emit_attempt(
                        attempt_number=attempt,
                        status_code=resp.status_code,
                        outcome="ok",
                        is_final=True,
                        duration_ms=elapsed_ms,
                    )
                    return resp.text
                if resp.status_code in _TRANSIENT_STATUS:
                    self._emit_attempt(
                        attempt_number=attempt,
                        status_code=resp.status_code,
                        outcome="transient_http",
                        is_final=(attempt == self.max_retries),
                        duration_ms=elapsed_ms,
                    )
                    last_error = FetchError(
                        f"Transient status {resp.status_code} for {url}"
                    )
                    continue
                self._emit_attempt(
                    attempt_number=attempt,
                    status_code=resp.status_code,
                    outcome="http_error",
                    is_final=True,
                    duration_ms=elapsed_ms,
                )
                raise FetchError(
                    f"Non-retryable status {resp.status_code} for {url}"
                )
            except requests.RequestException as exc:  # network-level failure
                elapsed = time.perf_counter() - t0
                elapsed_ms = elapsed * 1000.0
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] ERR  {elapsed:5.2f}s  {exc}")
                self._emit_attempt(
                    attempt_number=attempt,
                    status_code=None,
                    outcome="request_error",
                    is_final=(attempt == self.max_retries),
                    duration_ms=elapsed_ms,
                )
                last_error = exc
        raise FetchError(f"Failed to fetch {url} after retries: {last_error}")

    def sleep_between(self) -> None:
        """Pause between requests to respect the site's rate limits."""
        if self.delay > 0:
            time.sleep(self.delay)
