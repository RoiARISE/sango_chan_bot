"""Regression test: todo reminders must not be unbounded.

Every "todo" mention used to start a task that lived until the owner replied
"やった". One account could create any number of them, and each one kept
posting reminders. The handler now caps active reminders per user and across
the whole bot.
"""

from __future__ import annotations

import asyncio

import fakes
import src.handlers.mention as mention
from src import config


def _event(owner: str) -> asyncio.Event:
    event = asyncio.Event()
    event.owner_id = owner  # type: ignore[attr-defined]
    return event


async def test_per_user_limit_rejects_without_starting_a_loop(handler, msk):
    for index in range(config.MAX_ACTIVE_TODOS_PER_USER):
        handler._todo_stop_events[f"existing-{index}"] = _event("user-1")

    note = fakes.note(nid="overflow", user_id="user-1", text="@bot todo 追加")
    await handler._handle_todo(note)

    assert not [
        params for name, params in msk.calls if name == "notes_reactions_create"
    ], "the over-limit todo should not be acknowledged"
    created = msk.created_notes()
    assert created, "the user should be told why the todo was not registered"
    assert "一度に" in created[0]["text"]


async def test_global_limit_rejects_new_users(handler, msk):
    for index in range(config.MAX_ACTIVE_TODOS):
        handler._todo_stop_events[f"global-{index}"] = _event(f"user-{index}")

    note = fakes.note(nid="global-overflow", user_id="new-user", text="@bot todo")
    await handler._handle_todo(note)

    created = msk.created_notes()
    assert created, "the user should be told that the bot is at capacity"
    assert "リマインダーがいっぱい" in created[0]["text"]


async def test_duplicate_event_keys_count_as_one(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "MAX_ACTIVE_TODOS_PER_USER", 1)
    event = _event("user-1")
    handler._todo_stop_events["original"] = event
    handler._todo_stop_events["reminder"] = event  # same event under two ids

    note = fakes.note(nid="duplicate", user_id="user-1", text="@bot todo")
    await handler._handle_todo(note)

    created = msk.created_notes()
    assert created and "一度に1件" in created[0]["text"]


async def test_under_limit_still_starts_a_reminder(handler, msk, monkeypatch):
    calls = {"n": 0}

    async def fake_wait_for(awaitable, timeout=None):
        calls["n"] += 1
        awaitable.close()  # type: ignore[attr-defined]
        if calls["n"] == 1:
            raise asyncio.TimeoutError
        return await asyncio.Event().wait()

    monkeypatch.setattr(mention.asyncio, "wait_for", fake_wait_for)

    task = asyncio.create_task(handler._handle_todo(
        fakes.note(nid="ok-todo", user_id="user-1", text="@bot todo 牛乳")
    ))
    try:
        started = await fakes.wait_until(
            lambda: any(
                "これやった？" in params.get("text", "")
                for params in msk.created_notes()
            )
        )
        assert started, "a todo under the limit should still produce a reminder"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
