"""Tests for CLI exit codes, which systemd uses to detect failed runs."""

import pytest

from scraper import cli
from scraper.fetcher import FetchBlocked
from scraper.runner import RunSummary


def test_returns_zero_on_clean_run(monkeypatch):
    summary = RunSummary()
    summary.fetched = 5
    summary.new = 5
    monkeypatch.setattr(cli, "run", lambda **_: summary)
    assert cli.main(["--hours", "24"]) == 0


def test_returns_zero_on_quiet_day_without_errors(monkeypatch):
    summary = RunSummary()
    monkeypatch.setattr(cli, "run", lambda **_: summary)
    assert cli.main(["--hours", "24"]) == 0


def test_returns_one_when_blocked(monkeypatch):
    def boom(**_kwargs):
        raise FetchBlocked("HTTP 503 with Retry-After 3600s")

    monkeypatch.setattr(cli, "run", boom)
    assert cli.main(["--hours", "24"]) == 1


def test_returns_one_when_nothing_fetched_but_errors(monkeypatch):
    summary = RunSummary()
    summary.errors = 2
    monkeypatch.setattr(cli, "run", lambda **_: summary)
    assert cli.main(["--hours", "24"]) == 1


def test_returns_two_on_unknown_city(monkeypatch):
    monkeypatch.setattr(
        cli, "run", lambda **_: pytest.fail("run must not be called")
    )
    assert cli.main(["--cities", "karachi"]) == 2
