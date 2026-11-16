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
    llm.clear_runtime_state()
    yield
    llm.clear_runtime_state()


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
    store.set_profile("user-1", "猫が好き", "みー")
    store.change_intimacy("user-1", 1, "みー")
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "返事", "reason": ""}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        for turn in range(1, 9):
            result = await llm.run_llm(
                "user-1",
                "みー",
                f"メッセージ{turn}",
                is_reply=(turn > 1),
                store=store,
                audience=Audience("public"),
            )
            assert result["action"] == "reply"

        result = await llm.run_llm(
            "user-1",
            "みー",
            "まだ話す？",
            is_reply=True,
            store=store,
            audience=Audience("public"),
        )
        await asyncio.sleep(0)

    assert result == {
        "action": "react",
        "reaction": "💤",
        "reply": "",
        "reason": "safety_turn_limit_reached",
    }
    assert chat.await_count == 8
    update.assert_awaited_once()
    uid, uname, history_arg, prof_arg, intimacy_arg, store_arg = update.await_args.args
    assert (uid, uname, prof_arg, intimacy_arg, store_arg) == ("user-1", "みー", "猫が好き", 1, store)
    assert len(history_arg) == llm.MAX_HISTORY
    assert llm.user_memories["user-1"] == []
    assert llm.user_turns["user-1"] == 0
    # 8往復目は convo_context に「8 ターン目」と伝わっていることも確認
    assert "8 ターン目" in chat.await_args_list[-1].kwargs["convo_context"]


async def test_new_mention_resets_turn_counter_after_long_conversation():
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "返事", "reason": ""}
    )

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        for turn in range(1, 9):
            await llm.run_llm("user-1", "みー", f"m{turn}", is_reply=(turn > 1))

        assert llm.user_turns["user-1"] == 8

        # 新規メンションなら1ターン目からやり直せる
        result = await llm.run_llm("user-1", "みー", "別の話", is_reply=False)

    assert result["action"] == "reply"
    assert llm.user_turns["user-1"] == 1
    assert "1 ターン目" in chat.await_args_list[-1].kwargs["convo_context"]


async def test_concurrent_new_mention_during_turn_8_resets_inside_lock():
    turn8_entered = asyncio.Event()
    release_turn8 = asyncio.Event()

    async def fake_chat(messages, **kwargs):
        if "m8" in messages[-1]["content"]:
            turn8_entered.set()
            await release_turn8.wait()
            return {"action": "reply", "reaction": "❤️", "reply": "8回目の返事", "reason": ""}
        return {"action": "reply", "reaction": "❤️", "reply": "新しい返事", "reason": ""}

    chat = mock.AsyncMock(side_effect=fake_chat)

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        for turn in range(1, 8):
            await llm.run_llm("user-1", "みー", f"m{turn}", is_reply=(turn > 1))

        task8 = asyncio.create_task(llm.run_llm("user-1", "みー", "m8", is_reply=True))
        await turn8_entered.wait()

        task_new = asyncio.create_task(llm.run_llm("user-1", "みー", "別の話", is_reply=False))
        await asyncio.sleep(0)

        release_turn8.set()
        res8, res_new = await asyncio.gather(task8, task_new)

    assert res8["action"] == "reply"
    assert res_new["action"] == "reply"
    assert res_new["reply"] == "新しい返事"
    assert llm.user_turns["user-1"] == 1
    assert len(llm.user_memories["user-1"]) == 2
    assert "別の話" in llm.user_memories["user-1"][0]["content"]
    assert llm.user_memories["user-1"][1]["content"] == "新しい返事"


async def test_llm_error_does_not_increment_turn_counter():
    chat = mock.AsyncMock(
        side_effect=[
            {"action": "reply", "reaction": "❤️", "reply": "1回目", "reason": ""},
            RuntimeError("upstream down"),
            {"action": "reply", "reaction": "❤️", "reply": "リトライ成功", "reason": ""},
        ]
    )

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm("user-1", "みー", "こんにちは", is_reply=False)
        assert llm.user_turns["user-1"] == 1

        err_result = await llm.run_llm("user-1", "みー", "失敗する話", is_reply=True)
        assert err_result["reason"] == "run_llm_exception"
        assert llm.user_turns["user-1"] == 1

        ok_result = await llm.run_llm("user-1", "みー", "リトライ", is_reply=True)
        assert ok_result["action"] == "reply"
        assert llm.user_turns["user-1"] == 2


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
            image_urls=["https://media.example/a.png"],
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


async def test_reply_session_updates_profile_after_debounce_delay(store):
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "それはいいね", "reason": ""}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm, "PROFILE_UPDATE_DELAY", 0.01), \
         mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        result = await llm.run_llm(
            "user-1",
            "みー",
            "猫が好きなんです",
            is_reply=False,
            store=store,
            audience=Audience("public"),
        )
        assert result["action"] == "reply"
        update.assert_not_awaited()

        await asyncio.sleep(0.04)

    update.assert_awaited_once()
    uid, uname, history_arg, _, _, store_arg = update.await_args.args
    assert (uid, uname, store_arg) == ("user-1", "みー", store)
    assert [m["role"] for m in history_arg] == ["user", "assistant"]
    assert "猫が好きなんです" in history_arg[0]["content"]
    assert history_arg[1]["content"] == "それはいいね"
    assert update.await_args.kwargs["delay"] == 0.0
    # スレッド継続のため履歴自体は残しつつ、分析済み位置が進んでいること
    assert len(llm.user_memories["user-1"]) == 2
    assert llm.user_analyzed_upto["user-1"] == 2


async def test_consecutive_replies_debounce_and_analyze_once(store):
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "なるほど", "reason": ""}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm, "PROFILE_UPDATE_DELAY", 0.03), \
         mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        await llm.run_llm(
            "user-1", "みー", "話1", is_reply=False, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0.01)
        await llm.run_llm(
            "user-1", "みー", "話2", is_reply=True, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0.06)

    update.assert_awaited_once()
    history_arg = update.await_args.args[2]
    assert len(history_arg) == 4
    assert "話1" in history_arg[0]["content"]
    assert "話2" in history_arg[2]["content"]


async def test_resuming_thread_after_debounce_only_analyzes_new_turns(store):
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "返事", "reason": ""}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm, "PROFILE_UPDATE_DELAY", 0.01), \
         mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        await llm.run_llm(
            "user-1", "みー", "古い話", is_reply=False, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0.04)
        assert update.await_count == 1

        await llm.run_llm(
            "user-1", "みー", "新しい話", is_reply=True, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0.04)

    assert update.await_count == 2
    second_history = update.await_args_list[1].args[2]
    assert len(second_history) == 2
    assert "新しい話" in second_history[0]["content"]
    assert all("古い話" not in m["content"] for m in second_history)


async def test_new_mention_flushes_pending_reply_session_before_reset(store):
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "やあ", "reason": ""}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm, "PROFILE_UPDATE_DELAY", 60.0), \
         mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        await llm.run_llm(
            "user-1", "みー", "前の会話", is_reply=False, store=store, audience=Audience("public")
        )
        update.assert_not_awaited()

        await llm.run_llm(
            "user-1", "みー", "別の新しい話", is_reply=False, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0)

    update.assert_awaited_once()
    flushed_history = update.await_args.args[2]
    assert len(flushed_history) == 2
    assert "前の会話" in flushed_history[0]["content"]
    assert len(llm.user_memories["user-1"]) == 2
    assert "別の新しい話" in llm.user_memories["user-1"][0]["content"]
    assert llm.user_turns["user-1"] == 1
    assert llm.user_analyzed_upto["user-1"] == 0


async def test_fade_out_after_reply_cancels_debounce_timer_without_double_update(store):
    chat = mock.AsyncMock(
        side_effect=[
            {"action": "reply", "reaction": "❤️", "reply": "続き", "reason": ""},
            {"action": "react", "reaction": "👍", "reply": "", "reason": "done"},
        ]
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm, "PROFILE_UPDATE_DELAY", 0.01), \
         mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        await llm.run_llm(
            "user-1", "みー", "最初の話", is_reply=False, store=store, audience=Audience("public")
        )
        await llm.run_llm(
            "user-1", "みー", "ありがとう", is_reply=True, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0.04)

    update.assert_awaited_once()
    history_arg = update.await_args.args[2]
    assert len(history_arg) == 3
    assert "最初の話" in history_arg[0]["content"]
    assert "ありがとう" in history_arg[2]["content"]


async def test_overlapping_background_updates_run_serially_with_fresh_store_state(store):
    seen_profiles: list[tuple[str, int]] = []
    first_started = asyncio.Event()

    async def fake_analyze(history, current_profile, current_intimacy, user_name):
        seen_profiles.append((current_profile, current_intimacy))
        if len(seen_profiles) == 1:
            first_started.set()
            await asyncio.sleep(0.02)
            return {"description": "一次情報", "intimacy_change": 1}
        return {"description": f"{current_profile}＋二次情報", "intimacy_change": 0}

    with mock.patch.object(llm.openrouter, "analyze_user_interaction", side_effect=fake_analyze):
        llm._append_turn("user-1", {"role": "user", "content": "話1"}, Audience("public"))
        t1 = llm._schedule_profile_update("user-1", "みー", store, delay=0.0)
        await first_started.wait()

        llm._append_turn("user-1", {"role": "user", "content": "話2"}, Audience("public"))
        t2 = llm._schedule_profile_update("user-1", "みー", store, delay=0.0)
        await asyncio.gather(t1, t2)

    assert seen_profiles == [("", 0), ("一次情報", 1)]
    assert store.get_profile("user-1") == "一次情報＋二次情報"
    assert store.get_intimacy("user-1") == 1


async def test_flush_pending_profile_updates_runs_waiting_timers_on_shutdown(store):
    chat = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "おはよう", "reason": ""}
    )
    analysis = mock.AsyncMock(return_value={"description": "朝型", "intimacy_change": 1})

    with mock.patch.object(llm, "PROFILE_UPDATE_DELAY", 60.0), \
         mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm.openrouter, "analyze_user_interaction", analysis):
        await llm.run_llm(
            "user-1", "みー", "おはよう！", is_reply=False, store=store, audience=Audience("public")
        )
        assert "user-1" in llm.user_profile_timers
        assert store.get_profile("user-1") == ""

        await llm.flush_pending_profile_updates(timeout=1.0)

    analysis.assert_awaited_once()
    assert store.get_profile("user-1") == "朝型"
    assert store.get_intimacy("user-1") == 1
    assert "user-1" not in llm.user_profile_timers
