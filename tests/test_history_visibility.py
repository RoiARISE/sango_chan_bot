"""会話履歴の可視性フィルタの回帰テスト。

非公開ノートで交わした内容が、より広い可視性の返信で LLM に渡らないことを
確認する。履歴の保存形式は従来どおり ``{"role", "content"}`` のままで、
可視性は別のリストで同じ順序を保つ。
"""

from __future__ import annotations

from unittest import mock

import pytest

import fakes
import src.handlers.mention as mention
import src.services.llm as llm


@pytest.fixture(autouse=True)
def clean_memory():
    llm.user_memories.clear()
    llm.user_memory_visibilities.clear()
    llm.user_locks.clear()
    yield
    llm.user_memories.clear()
    llm.user_memory_visibilities.clear()
    llm.user_locks.clear()


def _reply(text: str = "わかった") -> dict:
    return {"action": "reply", "reaction": "❤️", "reply": text, "reason": ""}


def _contents(messages: list[dict]) -> list[str]:
    return [str(message["content"]) for message in messages]


async def test_specified_history_is_not_sent_to_public_reply():
    llm.user_memories["user-1"] = [
        {"role": "user", "content": "実は引っ越すんだ"},
        {"role": "assistant", "content": "それは内緒だね"},
    ]
    llm.user_memory_visibilities["user-1"] = ["specified", "specified"]
    chat = mock.AsyncMock(return_value=_reply())

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "最近どう？", is_reply=True, visibility="public"
        )

    contents = _contents(chat.await_args.args[0])
    assert not any("引っ越す" in content for content in contents)
    assert not any("内緒" in content for content in contents)
    assert contents[-1] == "[みーさんからのメッセージ]\n最近どう？"


async def test_specified_history_is_kept_for_specified_reply():
    llm.user_memories["user-1"] = [
        {"role": "user", "content": "実は引っ越すんだ"},
        {"role": "assistant", "content": "それは内緒だね"},
    ]
    llm.user_memory_visibilities["user-1"] = ["specified", "specified"]
    chat = mock.AsyncMock(return_value=_reply())

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "続きの話", is_reply=True, visibility="specified"
        )

    contents = _contents(chat.await_args.args[0])
    assert any("引っ越す" in content for content in contents)
    assert any("内緒" in content for content in contents)


@pytest.mark.parametrize(
    ("recorded", "current", "expected"),
    [
        ("specified", "specified", True),
        ("specified", "followers", False),
        ("specified", "public", False),
        ("followers", "followers", True),
        ("followers", "home", False),
        ("followers", "public", False),
        ("home", "home", True),
        ("home", "public", False),
        ("public", "specified", True),
        ("public", "followers", True),
        ("public", "public", True),
    ],
)
async def test_history_is_filtered_by_visibility_rank(recorded, current, expected):
    llm.user_memories["user-1"] = [{"role": "user", "content": "テスト用の秘密"}]
    llm.user_memory_visibilities["user-1"] = [recorded]
    chat = mock.AsyncMock(return_value=_reply())

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "今回の話", is_reply=True, visibility=current
        )

    contents = _contents(chat.await_args.args[0])
    assert any("テスト用の秘密" in content for content in contents) is expected


async def test_assistant_reply_inherits_the_visibility_of_its_turn():
    chat = mock.AsyncMock(return_value=_reply("秘密の返事"))

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "秘密の話", is_reply=False, visibility="followers"
        )

    history = llm.user_memories["user-1"]
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert llm.user_memory_visibilities["user-1"] == ["followers", "followers"]
    assert all(set(message) == {"role", "content"} for message in history)

    chat.reset_mock()
    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "公開の話", is_reply=True, visibility="public"
        )

    contents = _contents(chat.await_args.args[0])
    assert not any("秘密" in content for content in contents)


async def test_new_mention_resets_history_and_visibility():
    llm.user_memories["user-1"] = [{"role": "user", "content": "前の秘密"}]
    llm.user_memory_visibilities["user-1"] = ["specified"]
    chat = mock.AsyncMock(return_value=_reply())

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "はじめまして", is_reply=False, visibility="public"
        )

    contents = _contents(chat.await_args.args[0])
    assert not any("前の秘密" in content for content in contents)
    assert llm.user_memory_visibilities["user-1"] == ["public", "public"]


async def test_truncation_keeps_visibility_aligned():
    llm.user_memories["user-1"] = [
        {"role": "user", "content": f"過去{i}"} for i in range(llm.MAX_HISTORY)
    ]
    llm.user_memory_visibilities["user-1"] = ["public"] * llm.MAX_HISTORY
    chat = mock.AsyncMock(return_value=_reply())

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "新しい話", is_reply=True, visibility="public"
        )

    assert len(llm.user_memories["user-1"]) == llm.MAX_HISTORY
    assert len(llm.user_memory_visibilities["user-1"]) == llm.MAX_HISTORY
    assert set(llm.user_memory_visibilities["user-1"]) == {"public"}


async def test_seed_history_without_visibility_metadata_still_works():
    llm.user_memories["user-1"] = [
        {"role": "user", "content": "古い履歴"},
        {"role": "assistant", "content": "古い返事"},
    ]
    chat = mock.AsyncMock(return_value=_reply())

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "続き", is_reply=True, visibility="public"
        )

    contents = _contents(chat.await_args.args[0])
    assert any("古い履歴" in content for content in contents)


async def test_mention_handler_passes_note_visibility_to_llm(handler):
    run_llm = mock.AsyncMock(return_value=_reply())

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler._handle_llm(
            fakes.note(nid="n1", text="@bot ひみつの話", visibility="specified")
        )
        assert await fakes.wait_until(lambda: run_llm.await_count == 1)

    assert run_llm.await_args.kwargs["visibility"] == "specified"
