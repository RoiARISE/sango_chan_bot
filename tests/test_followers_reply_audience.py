"""Regression test: replies to non-public notes must not widen the audience.

Misskey's ``followers`` / ``home`` visibility is relative to the note author.
Copying it into the bot's reply publishes the reply to the bot's followers,
which may not include the original audience. The reply is narrowed to the
author with ``specified`` visibility instead.
"""

from __future__ import annotations

import fakes
import src.handlers.timeline as timeline
from src.handlers.timeline import TimelineHandler
from src.utils import reply_audience


def test_followers_note_is_narrowed_to_the_author():
    note = fakes.note(user_id="author", visibility="followers")
    assert reply_audience(note) == ("specified", ["author"])


def test_home_note_is_narrowed_to_the_author():
    note = fakes.note(user_id="author", visibility="home")
    assert reply_audience(note) == ("specified", ["author"])


def test_public_note_keeps_its_visibility():
    note = fakes.note(user_id="author", visibility="public")
    assert reply_audience(note) == ("public", None)


def test_specified_note_keeps_its_visibility():
    note = fakes.note(user_id="author", visibility="specified")
    assert reply_audience(note) == ("specified", None)


def test_mention_reply_to_followers_note_is_specified(handler):
    note = fakes.note(user_id="author", visibility="followers")
    params = handler._get_reply_kwargs(note, "返信")
    assert params["visibility"] == "specified"
    assert params["visible_user_ids"] == ["author"]


def test_specified_mention_still_includes_the_original_audience(handler):
    note = fakes.note(
        user_id="author", visibility="specified", visibleUserIds=["other"]
    )
    params = handler._get_reply_kwargs(note, "返信")
    assert params["visibility"] == "specified"
    assert set(params["visible_user_ids"]) == {"author", "other"}


async def test_timeline_reply_to_followers_note_is_specified(msk, store, monkeypatch):
    monkeypatch.setattr(timeline.random, "randint", lambda _a, _b: 1)
    handler = TimelineHandler(msk, store, msk.my_id)
    note = fakes.note(user_id="author", visibility="followers", text="さんごちゃん元気？")

    await handler.handle(note)

    created = msk.created_notes()
    assert created, "the timeline handler did not reply"
    assert created[0]["visibility"] == "specified"
    assert created[0]["visible_user_ids"] == ["author"]
