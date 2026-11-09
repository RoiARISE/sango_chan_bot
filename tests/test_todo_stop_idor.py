"""Regression test: a third party must not cancel someone else's Todo.

``MentionHandler.handle()`` stops a reminder when a note replying to a tracked
note contains "やった". It must also verify that the replier is the user who
created the Todo. Without that check any mutual follower who can see the
(public) reminder can silently cancel another user's reminder.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

import fakes
import src.handlers.mention as mention


async def test_attacker_cannot_stop_victims_reminder(handler, msk):
    victim_id = "victim-id"
    attacker_id = "attacker-user-id"

    victim_note = fakes.note(
        nid="victim-todo-note",
        user_id=victim_id,
        text="@bot todo 牛乳を買う",
    )

    # Capture the reminder note that the handler posts for the victim.
    reminder: dict[str, str] = {}
    original_notes_create = msk.notes_create

    def notes_create(**params):
        result = original_notes_create(**params)
        if "これやった？" in params.get("text", ""):
            reminder["id"] = result["createdNote"]["id"]
        return result

    msk.notes_create = notes_create  # type: ignore[method-assign]

    # Let the reminder loop create exactly one reminder, then block forever so
    # the victim's reminder state stays registered while the attacker acts.
    wait_calls = {"n": 0}

    async def fake_wait_for(awaitable, timeout=None):
        wait_calls["n"] += 1
        awaitable.close()  # type: ignore[attr-defined]
        if wait_calls["n"] == 1:
            raise asyncio.TimeoutError
        return await asyncio.Event().wait()

    todo_task = asyncio.create_task(handler._handle_todo(victim_note))
    with mock.patch.object(mention.asyncio, "wait_for", fake_wait_for), \
         mock.patch.object(mention.random, "randint", lambda a, b: 1):
        created = await fakes.wait_until(lambda: "id" in reminder)
        if not created:
            todo_task.cancel()
            await asyncio.gather(todo_task, return_exceptions=True)
            pytest.fail(f"reminder was not created; calls={msk.calls!r}")

        attacker_note = fakes.note(
            nid="attacker-yatta-note",
            user_id=attacker_id,
            text="@bot やった",
            replyId=reminder["id"],
        )
        await handler.handle(attacker_note)

        event = handler._todo_stop_events.get(reminder["id"])
        stopped = event is not None and event.is_set()

    todo_task.cancel()
    await asyncio.gather(todo_task, return_exceptions=True)

    assert not stopped, (
        "attacker (not the Todo owner) cancelled the victim's reminder by "
        f"replying 'やった' to reminder {reminder['id']}"
    )
