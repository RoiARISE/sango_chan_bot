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


async def test_timeline_ignores_nobot_users(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    msk.relation["description"] = "よろしくお願いします。 #nobot"

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(nid="n1", user_id="user-1", text="ねえさんごちゃん"))

    assert ("users_show", {"user_id": "user-1"}) in msk.calls
    assert not msk.created_notes()


async def test_timeline_accepts_fullwidth_and_case_insensitive_hashtag(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    msk.relation["description"] = "＃NoBot"

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(text="ねえさんごちゃん"))

    assert not msk.created_notes()


async def test_timeline_does_not_match_nobot_prefix_of_longer_hashtag(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    msk.relation["description"] = "#nobotです"

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(nid="n1", text="ねえさんごちゃん"))

    assert msk.created_notes()[-1]["reply_id"] == "n1"


async def test_timeline_ignores_plain_nobot_without_hash(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    msk.relation["description"] = "nobot"

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(nid="n1", text="ねえさんごちゃん"))

    assert msk.created_notes()[-1]["reply_id"] == "n1"


async def test_timeline_ignores_different_hashtag_with_nobot_prefix(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    msk.relation["description"] = "#nobotanical"

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(nid="n1", text="ねえさんごちゃん"))

    assert msk.created_notes()[-1]["reply_id"] == "n1"


async def test_timeline_skips_when_profile_cannot_be_fetched(msk, tmp_path):
    handler = make_handler(msk, tmp_path)

    with (
        mock.patch.object(timeline.random, "randint", return_value=1),
        mock.patch.object(msk, "users_show", side_effect=RuntimeError("boom")),
    ):
        await handler.handle(fakes.note(text="ねえさんごちゃん"))

    assert not msk.created_notes()


async def test_timeline_caches_nobot_check(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    msk.relation["description"] = "#nobot"

    with mock.patch.object(timeline.random, "randint", return_value=1):
        await handler.handle(fakes.note(nid="n1", text="ねえさんごちゃん"))
        msk.relation["description"] = ""
        await handler.handle(fakes.note(nid="n2", text="ねえさんごちゃん"))

    assert sum(1 for name, _ in msk.calls if name == "users_show") == 1
    assert not msk.created_notes()


async def test_timeline_refreshes_nobot_cache_after_ttl(msk, tmp_path):
    handler = make_handler(msk, tmp_path)
    msk.relation["description"] = "#nobot"

    with (
        mock.patch.object(timeline.random, "randint", return_value=1),
        mock.patch.object(timeline, "monotonic", side_effect=[0.0, 601.0, 601.0]),
    ):
        await handler.handle(fakes.note(nid="n1", text="ねえさんごちゃん"))
        msk.relation["description"] = ""
        await handler.handle(fakes.note(nid="n2", text="ねえさんごちゃん"))

    assert sum(1 for name, _ in msk.calls if name == "users_show") == 2
    assert msk.created_notes()[-1]["reply_id"] == "n2"


async def test_timeline_retries_nobot_check_after_fetch_failure(msk, tmp_path):
    handler = make_handler(msk, tmp_path)

    with (
        mock.patch.object(timeline.random, "randint", return_value=1),
        mock.patch.object(msk, "users_show", side_effect=[RuntimeError("boom"), {"description": ""}]),
    ):
        await handler.handle(fakes.note(nid="n1", text="ねえさんごちゃん"))
        await handler.handle(fakes.note(nid="n2", text="ねえさんごちゃん"))

    assert msk.created_notes()[-1]["reply_id"] == "n2"


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
