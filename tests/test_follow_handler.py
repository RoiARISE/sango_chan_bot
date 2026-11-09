"""Unit tests for ``src.handlers.follow.FollowHandler``."""

from __future__ import annotations

import fakes
from src.handlers.follow import FollowHandler


async def test_follow_handler_mentions_the_new_follower(msk, store):
    handler = FollowHandler(msk, store)

    await handler.handle({"id": "user-1", "username": "user_1"})

    reply = msk.created_notes()[-1]
    assert "@user_1" in reply["text"]
    assert "フォローありがとうございます" in reply["text"]
    assert "フォローバックするよ" in reply["text"]


async def test_follow_handler_uses_remote_mention(msk, store):
    handler = FollowHandler(msk, store)

    await handler.handle({"id": "user-1", "username": "user_1", "host": "remote.test"})

    assert "@user_1@remote.test" in msk.created_notes()[-1]["text"]
