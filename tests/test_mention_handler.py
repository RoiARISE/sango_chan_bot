"""Behavioural tests for ``src.handlers.mention.MentionHandler``.

The handler is the largest piece of the bot. The tests drive each command with a
recording Misskey double and check the note parameters that actually leave the
process: reply target, visibility, content warning hand-off, text shaping and
who is allowed to run each command.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

import fakes
import src.handlers.mention as mention


# ---------------------------------------------------------------------------
# reply parameter construction
# ---------------------------------------------------------------------------


def test_reply_kwargs_copies_note_id_and_visibility(handler):
    note = fakes.note(nid="n1", visibility="followers")
    params = handler._get_reply_kwargs(note, "やあ")

    assert params["text"] == "やあ"
    assert params["reply_id"] == "n1"
    assert params["visibility"] == "followers"
    assert "visible_user_ids" not in params


def test_reply_kwargs_falls_back_for_blank_text(handler):
    params = handler._get_reply_kwargs(fakes.note(), "   ")
    assert params["text"] == "……？"


def test_reply_kwargs_truncates_long_text(handler):
    params = handler._get_reply_kwargs(fakes.note(), "あ" * 3500)

    assert len(params["text"]) == 3000
    assert params["text"].endswith("（※文字数制限のため途中までを表示しています）")


def test_reply_kwargs_keeps_text_at_the_limit(handler):
    text = "あ" * 3000
    assert handler._get_reply_kwargs(fakes.note(), text)["text"] == text


def test_specified_visibility_builds_visible_user_ids_without_bot(handler):
    note = fakes.note(
        nid="n1",
        user_id="author",
        visibility="specified",
        visibleUserIds=["author", "bot-id", "other"],
    )
    params = handler._get_reply_kwargs(note, "ひみつ")

    assert params["visibility"] == "specified"
    assert set(params["visible_user_ids"]) == {"author", "other"}


def test_specified_visibility_uses_user_object_when_user_id_missing(handler):
    note = fakes.note(nid="n1", user_id="author", visibility="specified")
    note.pop("userId")
    note["visibleUserIds"] = ["bot-id"]

    params = handler._get_reply_kwargs(note, "ひみつ")
    assert set(params["visible_user_ids"]) == {"author"}


async def test_send_reply_passes_params_to_notes_create(handler, msk):
    await handler._send_reply(fakes.note(nid="n1"), "やあ")

    assert msk.calls[-1] == (
        "notes_create",
        {"text": "やあ", "reply_id": "n1", "visibility": "public"},
    )


async def test_send_reply_reraises_api_errors(handler, msk):
    msk.notes_create = mock.Mock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await handler._send_reply(fakes.note(), "やあ")


# ---------------------------------------------------------------------------
# follow / unfollow commands
# ---------------------------------------------------------------------------


async def test_follow_request_replies_when_relation_lookup_fails(handler, msk):
    msk.users_show = mock.Mock(side_effect=RuntimeError("down"))

    await handler._handle_follow_request(fakes.note(text="@bot フォローして"))

    assert "調子が悪い" in msk.created_notes()[-1]["text"]


async def test_follow_request_rejects_user_who_does_not_follow(handler, msk):
    msk.relation = {"isFollowed": False, "isFollowing": False}

    await handler._handle_follow_request(fakes.note(text="@bot フォローして"))

    assert msk.created_notes()[-1]["text"] == "……だれ？"


async def test_follow_request_reports_existing_follow(handler, msk):
    msk.relation = {"isFollowed": True, "isFollowing": True}

    await handler._handle_follow_request(
        fakes.note(user_id="user-1", text="@bot フォローして")
    )

    assert "もうフォローしてるよー" in msk.created_notes()[-1]["text"]


async def test_follow_request_follows_back_and_registers_user(handler, msk, store):
    msk.relation = {"isFollowed": True, "isFollowing": False}

    await handler._handle_follow_request(
        fakes.note(user_id="user-1", text="@bot フォローして", name="みー")
    )

    assert ("following_create", {"user_id": "user-1"}) in msk.calls
    assert store.get("user-1") is not None
    reply = msk.created_notes()[-1]
    assert "フォローバックしたよ" in reply["text"]
    assert "@user_user-1" in reply["text"]
    assert reply["reply_id"] == "note-1"


async def test_follow_request_reports_follow_failure(handler, msk):
    msk.relation = {"isFollowed": True, "isFollowing": False}
    msk.following_create = mock.Mock(side_effect=RuntimeError("boom"))

    await handler._handle_follow_request(fakes.note(text="@bot フォローして"))

    assert "うまくいかなかった" in msk.created_notes()[-1]["text"]


async def test_unfollow_request_replies_when_relation_lookup_fails(handler, msk):
    msk.users_show = mock.Mock(side_effect=RuntimeError("down"))

    await handler._handle_unfollow_request(fakes.note(text="@bot フォロー解除して"))

    assert "調子が悪い" in msk.created_notes()[-1]["text"]


async def test_unfollow_request_when_not_following(handler, msk):
    msk.relation = {"isFollowing": False}

    await handler._handle_unfollow_request(fakes.note(text="@bot フォロー解除して"))

    assert "もともとフォローしてないよー" in msk.created_notes()[-1]["text"]


async def test_unfollow_request_unfollows_and_forgets_user(handler, msk, store):
    msk.relation = {"isFollowing": True}
    store.ensure_user("user-1", "user_1")

    with mock.patch.object(mention.asyncio, "sleep", mock.AsyncMock()):
        await handler._handle_unfollow_request(fakes.note(text="@bot フォロー解除して"))

    assert ("following_delete", {"user_id": "user-1"}) in msk.calls
    assert store.get("user-1") is None
    assert "さよなら" in msk.created_notes()[0]["text"]


async def test_unfollow_request_reports_delete_failure(handler, msk):
    msk.relation = {"isFollowing": True}
    msk.following_delete = mock.Mock(side_effect=RuntimeError("boom"))

    with mock.patch.object(mention.asyncio, "sleep", mock.AsyncMock()):
        await handler._handle_unfollow_request(fakes.note(text="@bot フォロー解除して"))

    assert "うまくいかなかった" in msk.created_notes()[-1]["text"]


# ---------------------------------------------------------------------------
# cleanup command
# ---------------------------------------------------------------------------


async def test_cleanup_is_admin_only(handler, msk):
    await handler._handle_cleanup_command(fakes.note(user_id="user-1", text="@bot クリーンアップ"))

    assert "この機能は使える人が限られてる" in msk.created_notes()[-1]["text"]


async def test_cleanup_reports_callback_counts(msk, store):
    callback = mock.AsyncMock(return_value=(5, 2))
    handler = mention.MentionHandler(msk, store, "admin-id", cleanup_callback=callback)

    await handler._handle_cleanup_command(
        fakes.note(user_id="admin-id", text="@bot クリーンアップ")
    )

    callback.assert_awaited_once()
    texts = [params["text"] for params in msk.created_notes()]
    assert any("検証対象: 5人" in text and "削除/解除対象: 2人" in text for text in texts)


async def test_cleanup_reports_callback_failure(msk, store):
    callback = mock.AsyncMock(side_effect=RuntimeError("boom"))
    handler = mention.MentionHandler(msk, store, "admin-id", cleanup_callback=callback)

    await handler._handle_cleanup_command(
        fakes.note(user_id="admin-id", text="@bot クリーンアップ")
    )

    assert "クリーンアップ中にエラー" in msk.created_notes()[-1]["text"]


async def test_cleanup_without_callback(handler, msk):
    await handler._handle_cleanup_command(
        fakes.note(user_id="admin-id", text="@bot クリーンアップ")
    )

    assert "正しく設定されていない" in msk.created_notes()[-1]["text"]


# ---------------------------------------------------------------------------
# nickname commands
# ---------------------------------------------------------------------------


async def test_nickname_set_stores_sanitized_name(handler, msk, store):
    await handler._handle_nickname_set(fakes.note(user_id="user-1", text="@bot みーって呼んで"))

    assert store.get("user-1")["nickname"] == "みー"
    assert "これからはみーさんって呼ぶね" in msk.created_notes()[-1]["text"]


async def test_nickname_set_sanitizes_dangerous_input(handler, msk, store):
    payload = "$[x2] #tag"
    await handler._handle_nickname_set(
        fakes.note(user_id="user-1", text=f"@bot {payload}って呼んで")
    )

    stored = store.get("user-1")["nickname"]
    for marker in ("$[", "#tag"):
        assert marker not in stored


async def test_nickname_set_rejects_missing_name(handler, msk):
    await handler._handle_nickname_set(fakes.note(text="@bot って呼んで"))

    assert "うまく聞き取れなかった" in msk.created_notes()[-1]["text"]


async def test_nickname_set_rejects_too_long_name(handler, msk):
    await handler._handle_nickname_set(
        fakes.note(text="@bot " + "あ" * 11 + "って呼んで")
    )

    assert "長いかも" in msk.created_notes()[-1]["text"]


async def test_nickname_set_rejects_invalid_name(handler, msk):
    with mock.patch.object(mention.utils, "validate_nickname", return_value=False):
        await handler._handle_nickname_set(fakes.note(text="@bot みーって呼んで"))

    assert "だめかも" in msk.created_notes()[-1]["text"]


async def test_nickname_clear_resets_and_reports_names(handler, msk, store):
    store.set_nickname("user-1", "みー", "user_1")

    await handler._handle_nickname_clear(fakes.note(user_id="user-1", text="@bot 呼び名を忘れて"))

    assert store.get("user-1")["nickname"] == ""
    text = msk.created_notes()[-1]["text"]
    assert "「みー」" in text
    assert "user_1さん" in text


async def test_nickname_clear_works_when_profile_lookup_fails(handler, msk, store):
    store.set_nickname("user-1", "みー", "user_1")
    msk.users_show = mock.Mock(side_effect=RuntimeError("down"))

    await handler._handle_nickname_clear(fakes.note(user_id="user-1", text="@bot 呼び名を忘れて"))

    assert "user_user-1さん" in msk.created_notes()[-1]["text"]


async def test_nickname_clear_without_registration(handler, msk):
    await handler._handle_nickname_clear(fakes.note(user_id="user-1", text="@bot 呼び名を忘れて"))

    assert "もともと特別な呼び名" in msk.created_notes()[-1]["text"]


# ---------------------------------------------------------------------------
# speedtest command
# ---------------------------------------------------------------------------


async def test_speedtest_is_admin_only(handler, msk):
    await handler._handle_speedtest(fakes.note(user_id="user-1", text="@bot 回線速度を計測して"))

    assert "この機能は使える人が限られてる" in msk.created_notes()[-1]["text"]
    assert not any(name == "notes_create" and "計測" in params["text"]
                   for name, params in msk.calls)


async def test_speedtest_public_result_is_a_renote(handler, msk):
    result = "計測かんりょー。下り1.00Mbps、上り1.00Mbps、ping値1.00msだったよ。"

    with mock.patch.object(mention.speedtest, "run_speedtest", mock.AsyncMock(return_value=result)), \
         mock.patch.object(mention.asyncio, "sleep", mock.AsyncMock()):
        await handler._handle_speedtest(
            fakes.note(nid="cmd", user_id="admin-id", text="@bot 回線速度を計測して")
        )

    first, last = msk.created_notes()[0], msk.created_notes()[-1]
    assert first["reply_id"] == "cmd"
    assert first["visibility"] == "public"
    assert last["text"] == result
    assert last["renote_id"] == "cmd"
    assert last["visibility"] == "public"


async def test_speedtest_non_public_result_is_a_reply(handler, msk):
    result = "計測かんりょー。"

    with mock.patch.object(mention.speedtest, "run_speedtest", mock.AsyncMock(return_value=result)), \
         mock.patch.object(mention.asyncio, "sleep", mock.AsyncMock()):
        await handler._handle_speedtest(
            fakes.note(
                nid="cmd",
                user_id="admin-id",
                text="@bot 回線速度を計測して",
                visibility="specified",
                visibleUserIds=["admin-id"],
            )
        )

    last = msk.created_notes()[-1]
    assert last["reply_id"] == "cmd"
    assert last["visibility"] == "specified"


async def test_speedtest_timeout_is_reported(handler, msk):
    async def timing_out():
        await asyncio.sleep(0)
        raise asyncio.TimeoutError

    with mock.patch.object(mention.speedtest, "run_speedtest", timing_out), \
         mock.patch.object(mention.asyncio, "sleep", mock.AsyncMock()):
        await handler._handle_speedtest(
            fakes.note(user_id="admin-id", text="@bot 回線速度を計測して")
        )

    assert "1分経っても終わらない" in msk.created_notes()[-1]["text"]


async def test_speedtest_error_result_is_reported(handler, msk):
    result = "ごめん、計測中にエラーが起きちゃったみたい……"

    with mock.patch.object(mention.speedtest, "run_speedtest", mock.AsyncMock(return_value=result)), \
         mock.patch.object(mention.asyncio, "sleep", mock.AsyncMock()):
        await handler._handle_speedtest(
            fakes.note(user_id="admin-id", text="@bot 回線速度を計測して")
        )

    assert "何かがおかしいかも" in msk.created_notes()[-1]["text"]


# ---------------------------------------------------------------------------
# todo reminders
# ---------------------------------------------------------------------------


async def test_todo_registers_reaction_and_cleans_up_on_stop(handler, msk):
    async def immediate(_awaitable, timeout=None):
        _awaitable.close()
        return None

    note = fakes.note(nid="todo-1", user_id="user-1", text="@bot todo 牛乳を買う")

    with mock.patch.object(mention.asyncio, "wait_for", immediate), \
         mock.patch.object(mention.random, "randint", lambda a, b: 1):
        await handler._handle_todo(note)

    assert ("notes_reactions_create", {"note_id": "todo-1", "reaction": "👍"}) in msk.calls
    assert handler._todo_stop_events == {}


async def test_todo_reminder_uses_admin_specific_text(handler, msk):
    calls = {"n": 0}

    async def one_reminder(_awaitable, timeout=None):
        calls["n"] += 1
        _awaitable.close()
        if calls["n"] == 1:
            raise asyncio.TimeoutError
        return None

    note = fakes.note(nid="todo-1", user_id="admin-id", text="@bot todo 牛乳を買う")

    with mock.patch.object(mention.asyncio, "wait_for", one_reminder), \
         mock.patch.object(mention.random, "randint", lambda a, b: 1):
        await handler._handle_todo(note)

    reminder = msk.created_notes()[0]
    assert reminder["text"] == "ロイちゃん、これやった？"
    assert reminder["reply_id"] == "todo-1"


async def test_todo_owner_can_stop_reminder(handler, msk):
    event = asyncio.Event()
    event.owner_id = "user-1"
    handler._todo_stop_events["reminder-1"] = event

    await handler.handle(
        fakes.note(
            nid="reply-1",
            user_id="user-1",
            text="@bot やった",
            replyId="reminder-1",
        )
    )

    assert event.is_set()
    assert "お疲れさま" in msk.created_notes()[-1]["text"]


async def test_todo_stop_without_reply_target_is_ignored(handler, msk):
    await handler.handle(fakes.note(user_id="user-1", text="@bot やった"))
    assert not msk.created_notes()


# ---------------------------------------------------------------------------
# images and conversation scope
# ---------------------------------------------------------------------------


def test_extract_images_marks_sensitive_images(handler):
    note = fakes.note(
        files=[
            {"type": "image/png", "url": "https://media.example/a.png", "isSensitive": True},
            {"type": "text/plain", "url": "https://media.example/b.txt"},
            {"type": "image/jpeg"},
        ]
    )
    urls, sensitive = handler._extract_images_from_note(note)
    assert urls == ["https://media.example/a.png"]
    assert sensitive is True


def test_extract_images_without_images(handler):
    assert handler._extract_images_from_note(fakes.note()) == ([], False)
    assert handler._extract_images_from_note(fakes.note(files=[])) == ([], False)


async def test_fetch_parent_images_reads_reply_target(handler, msk):
    msk.parent_note = {
        "visibility": "public",
        "files": [{"type": "image/png", "url": "https://media.example/a.png"}],
    }
    urls, sensitive = await handler._fetch_parent_images("parent-1")

    assert urls == ["https://media.example/a.png"]
    assert sensitive is False
    assert ("notes_show", {"note_id": "parent-1"}) in msk.calls


async def test_fetch_parent_images_returns_empty_on_error(handler, msk):
    msk.notes_show = mock.Mock(side_effect=RuntimeError("down"))
    assert await handler._fetch_parent_images("parent-1") == ([], False)


async def test_is_reply_to_me_uses_embedded_parent(handler):
    note = fakes.note(replyId="parent-1", reply={"userId": "bot-id"})
    assert await handler._is_reply_to_me(note) is True

    note = fakes.note(replyId="parent-1", reply={"userId": "other"})
    assert await handler._is_reply_to_me(note) is False


async def test_is_reply_to_me_fetches_parent_when_missing(handler, msk):
    msk.parent_note = {"userId": "bot-id"}
    assert await handler._is_reply_to_me(fakes.note(replyId="parent-1")) is True

    msk.parent_note = {"userId": "other"}
    assert await handler._is_reply_to_me(fakes.note(replyId="parent-1")) is False


async def test_is_reply_to_me_handles_missing_target(handler, msk):
    assert await handler._is_reply_to_me(fakes.note()) is False

    msk.notes_show = mock.Mock(side_effect=RuntimeError("down"))
    assert await handler._is_reply_to_me(fakes.note(replyId="parent-1")) is False


async def test_is_reply_to_me_without_bot_id(handler, store):
    old_id = store._my_id
    store._my_id = None
    try:
        note = fakes.note(replyId="parent-1", reply={"userId": "bot-id"})
        assert await handler._is_reply_to_me(note) is False
    finally:
        store._my_id = old_id


# ---------------------------------------------------------------------------
# LLM actions
# ---------------------------------------------------------------------------


async def test_llm_reply_posts_reply_and_clears_thinking_reaction(handler, msk):
    result = {"action": "reply", "reaction": "❤️", "reply": "やあ", "reason": ""}

    with mock.patch.object(mention.llm, "run_llm", mock.AsyncMock(return_value=result)):
        await handler._handle_llm(fakes.note(nid="n1", text="@bot こんにちは"))
        assert await fakes.wait_until(lambda: bool(msk.created_notes()))

    assert msk.created_notes()[-1]["text"] == "やあ"
    assert ("notes_reactions_create", {"note_id": "n1", "reaction": "💭"}) in msk.calls
    assert ("notes_reactions_delete", {"note_id": "n1"}) in msk.calls
    assert ("notes_reactions_create", {"note_id": "n1", "reaction": "❤️"}) in msk.calls


async def test_llm_react_only_adds_reaction(handler, msk):
    result = {"action": "react", "reaction": "👍", "reply": "", "reason": "done"}

    with mock.patch.object(mention.llm, "run_llm", mock.AsyncMock(return_value=result)):
        await handler._handle_llm(fakes.note(nid="n1", text="@bot うん"))
        assert await fakes.wait_until(
            lambda: ("notes_reactions_create", {"note_id": "n1", "reaction": "👍"}) in msk.calls
        )

    assert not msk.created_notes()


async def test_llm_none_does_not_post(handler, msk):
    result = {"action": "none", "reaction": "❤️", "reply": "", "reason": "seen"}

    with mock.patch.object(mention.llm, "run_llm", mock.AsyncMock(return_value=result)):
        await handler._handle_llm(fakes.note(nid="n1", text="@bot そう"))
        assert await fakes.wait_until(
            lambda: ("notes_reactions_delete", {"note_id": "n1"}) in msk.calls
        )

    assert not msk.created_notes()


# ---------------------------------------------------------------------------
# command intents and dice
# ---------------------------------------------------------------------------


async def test_intent_greeting_uses_fixed_reply_when_llm_is_disabled(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", False)
    run_llm = mock.AsyncMock()

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot こんにちは"))

    run_llm.assert_not_awaited()
    assert msk.created_notes()[-1]["text"] == "こんにちは、どうしたの？"


async def test_intent_greeting_passes_hint_to_llm_and_forces_reply(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "やあ", "reason": "ok"}
    )

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot こんにちは"))
        assert await fakes.wait_until(lambda: bool(msk.created_notes()))

    kwargs = run_llm.await_args.kwargs
    assert "挨拶" in kwargs["intent_hint"]
    assert msk.created_notes()[-1]["text"] == "やあ"


async def test_intent_reply_is_sent_when_llm_tries_to_react(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock(
        return_value={"action": "react", "reaction": "❤️", "reply": "", "reason": "done"}
    )

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot こんにちは"))
        assert await fakes.wait_until(lambda: bool(msk.created_notes()))

    assert msk.created_notes()[-1]["text"] == "こんにちは、どうしたの？"


async def test_fixed_intent_sangochaan_does_not_call_llm(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock()

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot さんごちゃーん"))

    run_llm.assert_not_awaited()
    assert msk.created_notes()[-1]["text"] == "は〜い"


async def test_fixed_intent_nyaan_does_not_call_llm(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock()

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot にゃーん"))

    run_llm.assert_not_awaited()
    assert msk.created_notes()[-1]["text"] == "にゃ〜ん"


async def test_nadenade_hint_says_sango_is_petted(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "えへへ", "reason": "ok"}
    )

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot なでなで"))
        assert await fakes.wait_until(lambda: bool(msk.created_notes()))

    hint = run_llm.await_args.kwargs["intent_hint"]
    assert "さんご" in hint
    assert "撫でられ" in hint


async def test_fixed_intent_ping_does_not_call_llm(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock()

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot ping"))

    run_llm.assert_not_awaited()
    assert msk.created_notes()[-1]["text"] == "pong？"


async def test_fixed_intent_ping_accepts_trailing_punctuation(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock()

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot ping!!!"))

    run_llm.assert_not_awaited()
    assert msk.created_notes()[-1]["text"] == "pong？"


async def test_ping_inside_english_word_goes_to_llm(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "LLMの返信", "reason": "ok"}
    )

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot wrapping"))
        assert await fakes.wait_until(lambda: bool(msk.created_notes()))

    run_llm.assert_awaited_once()
    assert msk.created_notes()[-1]["text"] == "LLMの返信"


async def test_reply_only_intent_is_ignored_without_a_reply(handler, msk):
    await handler.handle(fakes.note(text="@bot ちくわ大明神"))
    assert not msk.created_notes()

    await handler.handle(fakes.note(text="@bot ちくわ大明神", replyId="parent"))
    assert msk.created_notes()[-1]["text"] == "…なに？"


async def test_chikuwa_question_goes_to_llm(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "LLMの返信", "reason": "ok"}
    )

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot ちくわ大明神って何？"))
        assert await fakes.wait_until(lambda: bool(msk.created_notes()))

    run_llm.assert_awaited_once()
    assert msk.created_notes()[-1]["text"] == "LLMの返信"


async def test_time_intent_injects_the_current_time(handler, msk, monkeypatch):
    monkeypatch.setattr(mention.config, "LLM_ENABLE", True)
    run_llm = mock.AsyncMock(
        return_value={"action": "reply", "reaction": "❤️", "reply": "12:34:56", "reason": "ok"}
    )

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler.handle(fakes.note(text="@bot 今何時"))
        assert await fakes.wait_until(lambda: bool(msk.created_notes()))

    assert "現在時刻" in run_llm.await_args.kwargs["intent_hint"]


async def test_dice_replies_with_single_roll(handler, msk):
    with mock.patch.object(mention.responses, "roll_dice", return_value=[4]):
        await handler._handle_dice(fakes.note(text="1d6"))

    assert msk.created_notes()[-1]["text"] == "@user_user-1 4 だよ"


async def test_dice_replies_with_multiple_rolls(handler, msk):
    with mock.patch.object(mention.responses, "roll_dice", return_value=[1, 2, 3]):
        await handler._handle_dice(fakes.note(text="3d6"))

    assert msk.created_notes()[-1]["text"] == "@user_user-1 1, 2, 3 だよ"


async def test_dice_rejects_invalid_roll(handler, msk):
    with mock.patch.object(mention.responses, "roll_dice", return_value=None):
        await handler._handle_dice(fakes.note(text="0d6"))

    assert msk.created_notes()[-1]["text"] == "……うーん？"


async def test_dice_without_match_does_nothing(handler, msk):
    await handler._handle_dice(fakes.note(text="さいころ"))
    assert not msk.created_notes()


# ---------------------------------------------------------------------------
# handle() gating
# ---------------------------------------------------------------------------


async def test_handle_ignores_non_mutual_followers(handler, msk):
    msk.relation = {"isFollowing": False, "isFollowed": True}

    await handler.handle(fakes.note(user_id="user-1", text="@bot こんにちは"))

    assert not msk.created_notes()


async def test_handle_processes_admin_without_relation_check(handler, msk):
    msk.users_show = mock.Mock(side_effect=AssertionError("should not be called"))

    await handler.handle(fakes.note(user_id="admin-id", text="@bot クリーンアップ"))

    assert "正しく設定されていない" in msk.created_notes()[-1]["text"]


async def test_handle_stops_when_relation_lookup_fails(handler, msk):
    msk.users_show = mock.Mock(side_effect=RuntimeError("down"))

    await handler.handle(fakes.note(user_id="user-1", text="@bot こんにちは"))

    assert not msk.created_notes()
