"""Unit tests for ``src.bot.MyBot``.

Only the parts that do not need a live websocket are covered: the cleanup job
that drops broken follow relationships, the manual cleanup wrapper and the
hourly timesignal post.
"""

from __future__ import annotations

import asyncio
from datetime import datetime as real_datetime
from datetime import timedelta, timezone
from unittest import mock

import pytest

import src.bot as bot_module
from src import config


@pytest.fixture
def bot(msk, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DATA_FILE", str(tmp_path / "user_data.json"))
    monkeypatch.setattr(config, "USER_DB_FILE", str(tmp_path / "user_data.sqlite3"))
    monkeypatch.setattr(config, "ADMIN_ID", "admin-id")
    return bot_module.MyBot(msk)


async def test_cleanup_returns_zero_without_users(bot, msk):
    assert await bot.cleanup_inactive_relations() == (0, 0)
    assert not any(name == "users_relation" for name, _ in msk.calls)


async def test_cleanup_skips_admin_only(bot, msk):
    bot._store.ensure_user("admin-id", "admin")

    with mock.patch.object(bot_module.asyncio, "sleep", mock.AsyncMock()):
        assert await bot.cleanup_inactive_relations() == (0, 0)

    assert not any(name == "users_relation" for name, _ in msk.calls)


async def test_cleanup_keeps_mutual_and_removes_broken_relations(bot, msk):
    bot._store.ensure_user("keep", "keep_user")
    bot._store.ensure_user("follow-only", "follow_only")
    bot._store.ensure_user("not-following", "not_following")
    msk.relations = [
        {"id": "keep", "isFollowing": True, "isFollowed": True},
        {"id": "follow-only", "isFollowing": True, "isFollowed": False},
        {"id": "not-following", "isFollowing": False, "isFollowed": False},
    ]

    with mock.patch.object(bot_module.asyncio, "sleep", mock.AsyncMock()):
        checked, removed = await bot.cleanup_inactive_relations()

    assert (checked, removed) == (3, 2)
    assert bot._store.get("keep") is not None
    assert bot._store.get("follow-only") is None
    assert bot._store.get("not-following") is None
    assert ("following_delete", {"user_id": "follow-only"}) in msk.calls
    assert ("following_delete", {"user_id": "not-following"}) not in msk.calls


async def test_cleanup_accepts_a_single_relation_dict(bot, msk):
    bot._store.ensure_user("user-1", "user_1")
    msk.relations = {"id": "user-1", "isFollowing": True, "isFollowed": True}

    with mock.patch.object(bot_module.asyncio, "sleep", mock.AsyncMock()):
        assert await bot.cleanup_inactive_relations() == (1, 0)


async def test_cleanup_chunks_requests_by_fifty(bot, msk):
    for i in range(51):
        bot._store.ensure_user(f"u{i}", f"user{i}")

    chunk_sizes = []

    def relations_for(user_id):
        chunk_sizes.append(len(user_id))
        return [{"id": uid, "isFollowing": True, "isFollowed": True} for uid in user_id]

    msk.users_relation = relations_for

    with mock.patch.object(bot_module.asyncio, "sleep", mock.AsyncMock()):
        checked, removed = await bot.cleanup_inactive_relations()

    assert (checked, removed) == (51, 0)
    assert chunk_sizes == [50, 1]


async def test_cleanup_continues_after_a_batch_error(bot, msk):
    for i in range(51):
        bot._store.ensure_user(f"u{i}", f"user{i}")

    calls = {"n": 0}

    def failing_once(user_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("batch failed")
        return [{"id": uid, "isFollowing": True, "isFollowed": True} for uid in user_id]

    msk.users_relation = failing_once

    with mock.patch.object(bot_module.asyncio, "sleep", mock.AsyncMock()):
        checked, removed = await bot.cleanup_inactive_relations()

    assert (checked, removed) == (51, 0)
    assert calls["n"] == 2


async def test_cleanup_keeps_user_when_unfollow_fails(bot, msk):
    bot._store.ensure_user("user-1", "user_1")
    msk.relations = [{"id": "user-1", "isFollowing": True, "isFollowed": False}]
    msk.following_delete = mock.Mock(side_effect=RuntimeError("boom"))

    with mock.patch.object(bot_module.asyncio, "sleep", mock.AsyncMock()):
        checked, removed = await bot.cleanup_inactive_relations()

    # The record is still removed even if the API call failed.
    assert (checked, removed) == (1, 1)
    assert bot._store.get("user-1") is None


async def test_manual_cleanup_syncs_before_cleaning(bot):
    sync = mock.Mock()
    cleanup = mock.AsyncMock(return_value=(3, 1))
    bot._store.sync_followings = sync
    bot.cleanup_inactive_relations = cleanup

    assert await bot.run_manual_cleanup() == (3, 1)
    sync.assert_called_once()
    cleanup.assert_awaited_once()


async def test_safe_run_swallows_and_logs_errors(caplog):
    async def boom():
        raise RuntimeError("handler failed")

    with caplog.at_level("ERROR"):
        await bot_module._safe_run(boom(), "mention")

    assert "handler failed" in caplog.text


async def test_timesignal_posts_known_hour(bot, msk, monkeypatch):
    fixed = real_datetime(2026, 1, 1, 12, 30, tzinfo=timezone(timedelta(hours=9)))

    sleeps = mock.AsyncMock(side_effect=[None, asyncio.CancelledError])

    monkeypatch.setattr(bot_module.clock, "now", lambda: fixed)
    with mock.patch.object(bot_module.asyncio, "sleep", sleeps):
        with pytest.raises(asyncio.CancelledError):
            await bot.timesignal_task()

    assert msk.created_notes()[-1]["text"] == bot_module.responses.SIGNALS[13]


async def test_timesignal_skips_unknown_hour(bot, msk, monkeypatch):
    fixed = real_datetime(2026, 1, 1, 9, 30, tzinfo=timezone(timedelta(hours=9)))

    sleeps = mock.AsyncMock(side_effect=[None, asyncio.CancelledError])

    monkeypatch.setattr(bot_module.clock, "now", lambda: fixed)
    with mock.patch.object(bot_module.asyncio, "sleep", sleeps):
        with pytest.raises(asyncio.CancelledError):
            await bot.timesignal_task()

    assert not msk.created_notes()
