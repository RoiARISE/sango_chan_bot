"""Unit tests for ``src.clock``."""

from __future__ import annotations

import datetime as dt

from src import clock


def test_now_is_timezone_aware():
    now = clock.now()
    assert isinstance(now, dt.datetime)
    assert now.tzinfo is not None
    assert now.utcoffset() is not None


def test_today_matches_the_local_date_of_now(monkeypatch):
    fixed = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone(dt.timedelta(hours=9)))
    monkeypatch.setattr(clock, "now", lambda: fixed)

    assert clock.today() == "2026-01-02"
