"""Unit tests for the conversation memory in ``src.services.llm``.

``run_llm`` keeps per-user history in module globals, so every test starts from a
clean slate. The OpenRouter call is replaced with an ``AsyncMock``: no test
touches the network.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

import src.services.llm as llm
from src.utils import Audience


@pytest.fixture(autouse=True)
def clean_memory():
    llm.user_memories.clear()
    llm.user_memory_audiences.clear()
    llm.user_locks.clear()
    yield
    llm.user_memories.clear()
    llm.user_memory_audiences.clear()
    llm.user_locks.clear()


async def test_new_mention_resets_history_and_records_reply(store):
    llm.user_memories["user-1"] = [{"role": "user", "content": "前の会話"}]
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "やあ", "reason": ""}
    )

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        result = await llm.run_llm("user-1", "みー", "こんにちは", store=store)

    assert result["reply"] == "やあ"
    history = llm.user_memories["user-1"]
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert "[みーさんからのメッセージ]\nこんにちは" in history[0]["content"]
    assert history[1]["content"] == "やあ"


async def test_reply_keeps_existing_history():
    llm.user_memories["user-1"] = [
        {"role": "user", "content": "前の質問"},
        {"role": "assistant", "content": "前の返事"},
    ]
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "続き", "reason": ""}
    )

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm("user-1", "みー", "続きの話", is_reply=True)

    history = llm.user_memories["user-1"]
    assert history[0]["content"] == "前の質問"
    assert history[-1] == {"role": "assistant", "content": "続き"}


async def test_history_is_truncated_to_max_history():
    llm.user_memories["user-1"] = [
        {"role": "user", "content": f"過去{i}"} for i in range(llm.MAX_HISTORY)
    ]
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "最新", "reason": ""}
    )

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm("user-1", "みー", "新しい話", is_reply=True)

    history = llm.user_memories["user-1"]
    assert len(history) == llm.MAX_HISTORY
    assert history[-1] == {"role": "assistant", "content": "最新"}


async def test_turn_limit_ends_with_a_reaction(store):
    llm.user_memories["user-1"] = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(16)
    ]
    llm.user_memory_audiences["user-1"] = [Audience("public")] * 16
    chat = mock.AsyncMock()
    update = mock.AsyncMock()

    with mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        result = await llm.run_llm("user-1", "みー", "まだ話す？", is_reply=True, store=store)
        await asyncio.sleep(0)

    assert result == {
        "action": "react",
        "reaction": "💤",
        "reply": "",
        "reason": "safety_turn_limit_reached",
    }
    chat.assert_not_awaited()
    update.assert_awaited_once()
    assert llm.user_memories["user-1"] == []


@pytest.mark.parametrize("action", ["react", "none"])
async def test_fade_out_clears_history_and_updates_profile(action, store):
    llm.user_memories["user-1"] = [{"role": "user", "content": "こんにちは"}]
    llm.user_memory_audiences["user-1"] = [Audience("public")]
    chat = mock.AsyncMock(
        return_value={"action": action, "reaction": "👍", "reply": "", "reason": "done"}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        result = await llm.run_llm(
            "user-1", "みー", "うん", is_reply=True, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0)

    assert result["action"] == action
    assert llm.user_memories["user-1"] == []
    update.assert_awaited_once()


async def test_llm_errors_remove_the_pending_user_message():
    chat = mock.AsyncMock(side_effect=RuntimeError("upstream down"))

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        result = await llm.run_llm("user-1", "みー", "こんにちは")

    assert result["reason"] == "run_llm_exception"
    assert "upstream down" in result["reply"]
    assert llm.user_memories["user-1"] == []


async def test_empty_text_with_image_gets_a_placeholder():
    llm.user_memories["user-1"] = []
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "かわいい", "reason": ""}
    )

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1",
            "みー",
            "",
            image_data_urls=["data:image/png;base64,AAAA"],
            has_sensitive_image=True,
        )

    prompt = chat.await_args.args[0][0]["content"]
    assert "（画像が送信されました）" in prompt
    assert "センシティブ" in prompt


async def test_profile_update_writes_description_and_intimacy(store):
    analysis = mock.AsyncMock(return_value={"description": "チョコ好き", "intimacy_change": 2})

    with mock.patch.object(llm.asyncio, "sleep", mock.AsyncMock()), \
         mock.patch.object(llm.openrouter, "analyze_user_interaction", analysis):
        await llm._update_user_profile_in_background(
            "user-1", "みー", [{"role": "user", "content": "こんにちは"}], "", 0, store
        )

    assert store.get_profile("user-1") == "チョコ好き"
    assert store.get_intimacy("user-1") == 2


async def test_profile_update_ignores_empty_description(store):
    analysis = mock.AsyncMock(return_value={"description": "", "intimacy_change": 0})

    with mock.patch.object(llm.asyncio, "sleep", mock.AsyncMock()), \
         mock.patch.object(llm.openrouter, "analyze_user_interaction", analysis):
        await llm._update_user_profile_in_background(
            "user-1", "みー", [], "既存", 0, store
        )

    assert store.get_profile("user-1") == ""


async def test_profile_update_swallows_errors(store):
    analysis = mock.AsyncMock(side_effect=RuntimeError("analysis down"))

    with mock.patch.object(llm.asyncio, "sleep", mock.AsyncMock()), \
         mock.patch.object(llm.openrouter, "analyze_user_interaction", analysis):
        await llm._update_user_profile_in_background(
            "user-1", "みー", [], "", 0, store
        )

    assert store.get_profile("user-1") == ""
