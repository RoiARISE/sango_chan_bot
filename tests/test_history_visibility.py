"""会話履歴の聴衆フィルタの回帰テスト。

非公開のノートで交わした内容が、より広い聴衆の返信で LLM に渡らないことを
確認する。履歴の保存形式は従来どおり ``{"role", "content"}`` のままで、
聴衆は同じ長さ・同じ順序の別リストで持つ。
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

import fakes
import src.handlers.mention as mention
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


def _reply(text: str = "わかった") -> dict:
    return {"action": "reply", "reaction": "❤️", "reply": text, "reason": ""}


def _seed(history: list[dict], audiences: list[Audience]) -> None:
    llm.user_memories["user-1"] = history
    llm.user_memory_audiences["user-1"] = audiences


async def _run(audience: Audience, *, is_reply: bool = True, store=None) -> list[str] | None:
    chat = mock.AsyncMock(return_value=_reply())
    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "今回の話", is_reply=is_reply, store=store, audience=audience
        )
    if chat.await_count == 0:
        return None
    return [str(message["content"]) for message in chat.await_args.args[0]]


def _specified(*recipients: str) -> Audience:
    return Audience("specified", frozenset(recipients))


async def test_specified_history_is_not_sent_to_a_public_reply():
    _seed(
        [
            {"role": "user", "content": "実は引っ越すんだ"},
            {"role": "assistant", "content": "それは内緒だね"},
        ],
        [_specified("user-1"), _specified("user-1")],
    )

    contents = await _run(Audience("public"))

    assert not any("引っ越す" in content for content in contents)
    assert not any("内緒" in content for content in contents)
    assert contents[-1] == "[みーさんからのメッセージ]\n今回の話"


async def test_specified_history_is_sent_to_the_same_recipients():
    _seed(
        [
            {"role": "user", "content": "実は引っ越すんだ"},
            {"role": "assistant", "content": "それは内緒だね"},
        ],
        [_specified("user-1"), _specified("user-1")],
    )

    contents = await _run(_specified("user-1"))

    assert any("引っ越す" in content for content in contents)
    assert any("内緒" in content for content in contents)


async def test_specified_history_survives_when_the_current_recipients_are_a_subset():
    # 3 人で話した内容は、そのうちの 1 人との specified 返信には使える
    _seed(
        [{"role": "user", "content": "3人で話した秘密"}],
        [_specified("user-1", "user-2")],
    )

    contents = await _run(_specified("user-1"))

    assert any("3人で話した秘密" in content for content in contents)


async def test_specified_history_is_dropped_when_the_current_recipients_are_wider():
    _seed(
        [{"role": "user", "content": "2人だけの秘密"}],
        [_specified("user-1")],
    )

    contents = await _run(_specified("user-1", "user-2"))

    assert not any("2人だけの秘密" in content for content in contents)


@pytest.mark.parametrize(
    ("recorded", "current", "expected"),
    [
        ("specified", "followers", False),
        ("specified", "home", False),
        ("specified", "public", False),
        ("followers", "specified", False),
        ("followers", "followers", True),
        ("followers", "home", False),
        ("followers", "public", False),
        ("home", "specified", True),
        ("home", "followers", True),
        ("home", "home", True),
        ("home", "public", True),
        ("public", "specified", True),
        ("public", "followers", True),
        ("public", "home", True),
        ("public", "public", True),
    ],
)
async def test_history_is_filtered_by_audience_containment(recorded, current, expected):
    _seed([{"role": "user", "content": "ランクのテスト"}], [Audience(recorded)])

    contents = await _run(Audience(current))

    assert any("ランクのテスト" in content for content in contents) is expected


async def test_home_history_is_sent_to_a_public_reply():
    # home はグローバルタイムラインに流すかどうかの違いで、閲覧範囲は public と同じ
    _seed([{"role": "user", "content": "ホームで話した話"}], [Audience("home")])

    contents = await _run(Audience("public"))

    assert any("ホームで話した話" in content for content in contents)


async def test_assistant_reply_inherits_the_audience_of_its_turn():
    chat = mock.AsyncMock(return_value=_reply("秘密の返事"))
    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await llm.run_llm(
            "user-1", "みー", "秘密の話", is_reply=False, audience=_specified("user-1")
        )

    assert llm.user_memory_audiences["user-1"] == [_specified("user-1"), _specified("user-1")]
    assert all(set(message) == {"role", "content"} for message in llm.user_memories["user-1"])

    contents = await _run(Audience("public"))
    assert not any("秘密" in content for content in contents)


async def test_new_mention_resets_history_and_audiences():
    _seed([{"role": "user", "content": "前の秘密"}], [_specified("user-1")])

    contents = await _run(Audience("public"), is_reply=False)

    assert not any("前の秘密" in content for content in contents)
    assert llm.user_memory_audiences["user-1"] == [Audience("public"), Audience("public")]


async def test_truncation_keeps_audiences_aligned():
    history = [
        {"role": "user", "content": f"過去{i}"} for i in range(llm.MAX_HISTORY)
    ]
    _seed(history, [Audience("public")] * llm.MAX_HISTORY)

    await _run(Audience("public"))

    assert len(llm.user_memories["user-1"]) == llm.MAX_HISTORY
    assert len(llm.user_memory_audiences["user-1"]) == llm.MAX_HISTORY
    assert set(llm.user_memory_audiences["user-1"]) == {Audience("public")}


async def test_history_without_audience_is_not_sent():
    # 聴衆が分からない履歴は public とみなさない（fail-closed）
    _seed([{"role": "user", "content": "古い履歴"}], [])

    contents = await _run(Audience("public"))

    assert not any("古い履歴" in content for content in contents)


async def test_unknown_current_audience_still_keeps_public_history():
    # public の履歴は誰に見えても安全なので、今回の聴衆が不明でも渡してよい
    _seed([{"role": "user", "content": "公開の履歴"}], [Audience("public")])

    contents = await _run(Audience("unknown"))

    assert any("公開の履歴" in content for content in contents)


async def test_profile_update_is_skipped_when_the_session_contains_a_private_turn(store):
    _seed(
        [
            {"role": "user", "content": "公開の話"},
            {"role": "user", "content": "秘密の話"},
        ],
        [Audience("public"), _specified("user-1")],
    )
    chat = mock.AsyncMock(
        return_value={"action": "react", "reaction": "👍", "reply": "", "reason": "done"}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        await llm.run_llm(
            "user-1", "みー", "うん", is_reply=True, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0)

    update.assert_not_awaited()
    assert store.get_profile("user-1") == ""


async def test_profile_update_runs_for_a_home_session(store):
    # home は誰でも閲覧できるので、プロフィール要約に含めてよい
    _seed(
        [
            {"role": "user", "content": "公開の話"},
            {"role": "user", "content": "ホームの話"},
        ],
        [Audience("public"), Audience("home")],
    )
    chat = mock.AsyncMock(
        return_value={"action": "react", "reaction": "👍", "reply": "", "reason": "done"}
    )
    update = mock.AsyncMock()

    with mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        await llm.run_llm(
            "user-1", "みー", "うん", is_reply=True, store=store, audience=Audience("home")
        )
        await asyncio.sleep(0)

    update.assert_awaited_once()


async def test_profile_update_is_skipped_at_the_turn_limit_for_a_private_session(store):
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(18)
    ]
    _seed(history, [Audience("public")] * 17 + [_specified("user-1")])
    chat = mock.AsyncMock()
    update = mock.AsyncMock()

    with mock.patch.object(llm.openrouter, "chat_with_history", chat), \
         mock.patch.object(llm, "_update_user_profile_in_background", update):
        result = await llm.run_llm(
            "user-1", "みー", "まだ話す？", is_reply=True, store=store, audience=Audience("public")
        )
        await asyncio.sleep(0)

    assert result["reason"] == "safety_turn_limit_reached"
    update.assert_not_awaited()
    assert llm.user_memory_audiences["user-1"] == []


async def test_mention_handler_passes_the_note_audience(handler):
    run_llm = mock.AsyncMock(return_value=_reply())
    note = fakes.note(
        nid="n1",
        text="@bot ひみつの話",
        visibility="specified",
        visibleUserIds=["user-1", "bot-id", "user-2"],
    )

    with mock.patch.object(mention.llm, "run_llm", run_llm):
        await handler._handle_llm(note)
        assert await fakes.wait_until(lambda: run_llm.await_count == 1)

    assert run_llm.await_args.kwargs["audience"] == _specified("user-1", "user-2")


async def test_private_history_does_not_reach_a_public_reply_from_the_handler(handler):
    """Issue #15 の再現。specified の会話が public の返信に混ざらないこと。"""
    _seed(
        [
            {"role": "user", "content": "[みーさんからのメッセージ]\n実は引っ越すんだ"},
            {"role": "assistant", "content": "それは内緒だね"},
        ],
        [_specified("user-1"), _specified("user-1")],
    )
    chat = mock.AsyncMock(return_value=_reply("そうなんだ"))
    note = fakes.note(nid="n2", text="@bot これどう思う？", replyId="parent-1")

    with mock.patch.object(llm.openrouter, "chat_with_history", chat):
        await handler._handle_llm(note)
        assert await fakes.wait_until(lambda: chat.await_count == 1)

    contents = [str(message["content"]) for message in chat.await_args.args[0]]
    assert not any("引っ越す" in content for content in contents)
    assert not any("内緒" in content for content in contents)


async def test_parent_images_are_skipped_when_the_parent_is_narrower(handler, msk):
    msk.parent_note = {
        "visibility": "specified",
        "userId": "user-1",
        "visibleUserIds": ["user-1"],
        "files": [{"type": "image/png", "url": "https://media.example/secret.png"}],
    }

    urls, sensitive = await handler._fetch_parent_images("parent-1", Audience("public"))

    assert urls == []
    assert sensitive is False


async def test_parent_images_are_kept_for_a_home_parent(handler, msk):
    # home の親ノートは誰でも閲覧できるので、public 返信でも画像を使ってよい
    msk.parent_note = {
        "visibility": "home",
        "userId": "user-1",
        "files": [{"type": "image/png", "url": "https://media.example/home.png"}],
    }

    urls, _ = await handler._fetch_parent_images("parent-1", Audience("public"))

    assert urls == ["https://media.example/home.png"]


async def test_parent_images_are_kept_when_the_parent_covers_the_reply(handler, msk):
    msk.parent_note = {
        "visibility": "specified",
        "userId": "bot-id",
        "visibleUserIds": ["user-1"],
        "files": [{"type": "image/png", "url": "https://media.example/ok.png"}],
    }

    urls, _ = await handler._fetch_parent_images("parent-1", _specified("user-1"))

    assert urls == ["https://media.example/ok.png"]
