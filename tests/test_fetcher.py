"""Unit tests for the polite HTTP fetcher."""

import pytest
import requests

from scraper.fetcher import FetchError, Fetcher


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    """A stand-in for requests.Session that records calls and returns canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self.responses.pop(0)


def test_get_returns_text_on_200():
    session = FakeSession([FakeResponse(200, "<html>ok</html>")])
    fetcher = Fetcher(delay=0, session=session)
    assert fetcher.get("https://example.com") == "<html>ok</html>"
    assert session.calls == ["https://example.com"]


def test_get_retries_transient_then_succeeds():
    session = FakeSession(
        [
            FakeResponse(503, ""),
            FakeResponse(503, ""),
            FakeResponse(200, "<html>ok</html>"),
        ]
    )
    fetcher = Fetcher(delay=0, max_retries=3, backoff=0, session=session)
    assert fetcher.get("https://example.com") == "<html>ok</html>"
    assert len(session.calls) == 3


def test_get_raises_after_exhausting_retries():
    session = FakeSession([FakeResponse(503, ""), FakeResponse(503, "")])
    fetcher = Fetcher(delay=0, max_retries=2, backoff=0, session=session)
    with pytest.raises(FetchError):
        fetcher.get("https://example.com")


def test_get_raises_on_non_retryable_status():
    session = FakeSession([FakeResponse(404, "")])
    fetcher = Fetcher(delay=0, max_retries=3, backoff=0, session=session)
    with pytest.raises(FetchError):
        fetcher.get("https://example.com")


def test_get_raises_on_network_error():
    class BoomSession(FakeSession):
        def get(self, url, timeout=None):
            self.calls.append(url)
            raise requests.ConnectionError("boom")

    session = BoomSession([])
    fetcher = Fetcher(delay=0, max_retries=2, backoff=0, session=session)
    with pytest.raises(FetchError):
        fetcher.get("https://example.com")
    assert len(session.calls) == 2


def test_user_agent_set_on_session():
    session = FakeSession([FakeResponse(200, "")])
    Fetcher(delay=0, session=session)
    assert "User-Agent" in session.headers
