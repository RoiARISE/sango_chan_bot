"""Unit tests for ``src.handlers.timeline.TimelineHandler``."""

from __future__ import annotations

from unittest import mock

import fakes
import src.handlers.timeline as timeline
from src.handlers.timeline import TimelineHandler
from src.stores.user_store import UserStore


def make_handler(msk, tmp_path) -> TimelineHandler:
    store = UserStore(str(tmp_path / "user_data.json"), msk, msk.my_id)
    store.load()
    return TimelineHandler(msk, store, msk.my_id)


async def test_timeline_ignores_empty_notes(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    await handler.handle(fakes.note(text=""))
    await handler.handle(fakes.note(text=None))
    assert not msk.created_notes()


async def test_timeline_ignores_renotes(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    await handler.handle(fakes.note(text="さんごちゃん", renoteId="original"))
    assert not msk.created_notes()


async def test_timeline_ignores_own_notes(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    await handler.handle(fakes.note(user_id=msk.my_id, text="さんごちゃん"))
    assert not msk.created_notes()


async def test_timeline_ignores_mentions(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    await handler.handle(fakes.note(text="さんごちゃん", mentions=[msk.my_id]))
    assert not msk.created_notes()


async def test_timeline_ignores_notes_without_keywords(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    await handler.handle(fakes.note(text="今日はいい天気だね"))
    assert not msk.created_notes()


async def test_timeline_may_answer_a_call(msk, tmp_path):
    handler = make_handler(msk, tmp_path)

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(nid="n1", user_id="user-1", text="ねえさんごちゃん"))

    reply = msk.created_notes()[-1]
    assert reply["text"] == "呼んだ？ user_user-1さん"
    assert reply["reply_id"] == "n1"
    assert reply["visibility"] == "public"


async def test_timeline_can_skip_a_call_randomly(msk, tmp_path):
    handler = make_handler(msk, tmp_path)

    with mock.patch.object(timeline.random, "randint", return_value=2):
        await handler.handle(fakes.note(text="ねえさんごちゃん"))

    assert not msk.created_notes()


async def test_timeline_requires_text_around_the_call(msk, tmp_path):
    handler = make_handler(msk, tmp_path)

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(text="さんごちゃん"))

    assert not msk.created_notes()
