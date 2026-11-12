"""Unit tests for the text helpers in ``src.utils``.

These functions guard the values that end up in note text, so the tests focus on
the exact character-level behaviour: what gets neutralized, what is left alone,
and how mentions are built for local and federated users.
"""

from __future__ import annotations

import pytest

from src import utils

BIDI_CONTROLS = (
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
)


@pytest.mark.parametrize("control", BIDI_CONTROLS)
def test_sanitize_nickname_removes_bidi_controls(control):
    assert utils.sanitize_nickname(f"さ{control}んご") == "さんご"


@pytest.mark.parametrize(
    ("raw", "dangerous_sequence"),
    [
        ("<center>", "<center>"),
        ("$[x2 あ]", "$["),
        ("https://evil.example", "://"),
        ("[click](https://evil.example)", "]("),
        ("#tag", "#tag"),
        ("@victim", "@victim"),
        ("**bold**", "**"),
    ],
)
def test_sanitize_nickname_breaks_dangerous_sequences(raw, dangerous_sequence):
    sanitized = utils.sanitize_nickname(raw)
    assert dangerous_sequence not in sanitized
    assert "\u200b" in sanitized


def test_sanitize_nickname_keeps_plain_japanese():
    assert utils.sanitize_nickname("さんごちゃん") == "さんごちゃん"
    assert utils.sanitize_nickname("ロイ") == "ロイ"


def test_sanitize_nickname_is_idempotent_for_plain_text():
    once = utils.sanitize_nickname("ふつうの なまえ")
    assert utils.sanitize_nickname(once) == once


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@bot みーって呼んで", "みー"),
        ("@bot みーと呼んで", "みー"),
        ("みーって呼んで", "みー"),
        ("@bot さんごって呼んで\nありがとう", "さんご"),
        ("@bot みーって呼んで。", "みー"),
        ("@bot みーと呼んで、お願い", "みー"),
    ],
)
def test_extract_nickname(text, expected):
    assert utils.extract_nickname(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "こんにちは",
        "@bot って呼んで",
        "",
    ],
)
def test_extract_nickname_returns_none_when_missing(text):
    assert utils.extract_nickname(text) is None


def test_validate_nickname_rejects_empty_and_whitespace():
    assert utils.validate_nickname("") is False
    assert utils.validate_nickname("   ") is False
    assert utils.validate_nickname("\n\t") is False


def test_validate_nickname_accepts_visible_text():
    assert utils.validate_nickname("さんご") is True


def test_create_mention_string_for_local_user():
    assert utils.create_mention_string({"username": "sango"}) == "@sango"


def test_create_mention_string_for_remote_user():
    assert (
        utils.create_mention_string({"username": "sango", "host": "example.test"})
        == "@sango@example.test"
    )


def test_create_mention_string_without_username_is_empty():
    assert utils.create_mention_string({}) == ""
    assert utils.create_mention_string({"host": "example.test"}) == ""


# ---------------------------------------------------------------------------
# Audience
# ---------------------------------------------------------------------------


def test_audience_from_public_note_has_no_recipients():
    audience = utils.Audience.from_note({"visibility": "public", "userId": "user-1"})

    assert audience == utils.Audience("public", frozenset())


def test_audience_from_specified_note_excludes_the_bot():
    note = {
        "visibility": "specified",
        "userId": "author",
        "visibleUserIds": ["author", "bot-id", "other"],
    }

    audience = utils.Audience.from_note(note, "bot-id")

    assert audience.visibility == "specified"
    assert audience.recipients == frozenset({"author", "other"})


def test_audience_from_specified_note_falls_back_to_the_author():
    note = {"visibility": "specified", "user": {"id": "author"}, "visibleUserIds": ["bot-id"]}

    audience = utils.Audience.from_note(note, "bot-id")

    assert audience.recipients == frozenset({"author"})


def test_audience_without_visibility_is_unknown():
    assert utils.Audience.from_note({}).visibility == "unknown"
    assert utils.Audience.from_note({"visibility": "friends"}).visibility == "unknown"


def test_unknown_audience_covers_nothing():
    unknown = utils.Audience("unknown")

    assert not unknown.covers(utils.Audience("public"))
    assert not unknown.covers(unknown)


def test_public_audience_covers_everything():
    public = utils.Audience("public")

    assert public.covers(utils.Audience("specified", frozenset({"user-1"})))
    assert public.covers(utils.Audience("followers"))
    assert public.covers(utils.Audience("public"))


def test_specified_audience_requires_a_recipient_superset():
    audience = utils.Audience("specified", frozenset({"user-1", "user-2"}))

    assert audience.covers(utils.Audience("specified", frozenset({"user-1"})))
    assert not audience.covers(utils.Audience("specified", frozenset({"user-3"})))


@pytest.mark.parametrize(
    ("recorded", "current", "expected"),
    [
        ("followers", "followers", True),
        ("followers", "home", False),
        ("followers", "public", False),
        ("home", "followers", True),
        ("home", "home", True),
        ("home", "public", False),
    ],
)
def test_followers_and_home_follow_the_visibility_order(recorded, current, expected):
    assert utils.Audience(recorded).covers(utils.Audience(current)) is expected
