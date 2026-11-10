"""Unit tests for ``src.responses``: dice bounds, categories and time output."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from src import responses


def test_roll_dice_returns_requested_number_of_rolls():
    rolls = responses.roll_dice("3", "6")
    assert len(rolls) == 3
    assert all(1 <= value <= 6 for value in rolls)


def test_roll_dice_accepts_the_documented_upper_bounds():
    assert responses.roll_dice("10000", "10000000000") is not None


@pytest.mark.parametrize(
    ("count", "sides"),
    [
        ("0", "6"),
        ("3", "0"),
        ("-1", "6"),
        ("3", "-6"),
        ("10001", "6"),
        ("3", "10000000001"),
    ],
)
def test_roll_dice_rejects_out_of_range_values(count, sides):
    assert responses.roll_dice(count, sides) is None


@pytest.mark.parametrize(("count", "sides"), [("x", "6"), ("3", "y"), ("", "")])
def test_roll_dice_rejects_non_numeric_values(count, sides):
    assert responses.roll_dice(count, sides) is None


def test_get_random_response_returns_a_member_of_the_category():
    assert responses.get_random_response("go_work") in responses.GO_WORK
    assert responses.get_random_response("morning") in responses.MORNING


def test_get_random_response_unknown_category_is_empty():
    assert responses.get_random_response("does-not-exist") == ""


def test_get_current_time_response_has_hh_mm_ss():
    reply = responses.get_current_time_response()
    assert re.search(r"いまは \d{2}:\d{2}:\d{2} だよ", reply)


def test_get_current_time_response_uses_jst(monkeypatch):
    recorded = {}

    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            recorded["tz"] = tz
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=tz)

    monkeypatch.setattr(responses, "datetime", FakeDatetime)

    reply = responses.get_current_time_response()

    assert recorded["tz"] == timezone(timedelta(hours=9))
    assert "03:04:05" in reply
