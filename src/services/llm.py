import asyncio
import logging

from . import openrouter
from ..stores.user_store import UserStore
from ..utils import Audience

logger = logging.getLogger(__name__)

# 記憶を保存する辞書（botが起動している間だけ保持されます）
user_memories: dict = {}
# 各発言をどの聴衆のノートで交わしたか（user_memories と同じ長さ・同じ順序）
user_memory_audiences: dict[str, list[Audience]] = {}
# ユーザーごとの排他ロック
user_locks: dict[str, asyncio.Lock] = {}
# 過去何往復分の会話を覚えているか（いまのところ10件＝5往復に制限）
MAX_HISTORY = 10

# 聴衆が分からない発言は、最も狭いものとして扱う（fail-closed）
_UNKNOWN_AUDIENCE = Audience("unknown")


def _align_audiences(user_id: str) -> list[Audience]:
    """履歴の長さに聴衆リストを合わせる。

    直接履歴が差し替えられた場合は、情報の無いターンを unknown で埋める。
    unknown はどの聴衆も包含しないので、LLM には渡らない。
    """
    history = user_memories.setdefault(user_id, [])
    audiences = user_memory_audiences.setdefault(user_id, [])
    if len(audiences) < len(history):
        audiences.extend([_UNKNOWN_AUDIENCE] * (len(history) - len(audiences)))
    elif len(audiences) > len(history):
        del audiences[len(history):]
    return audiences


def _append_turn(user_id: str, message: dict, audience: Audience) -> None:
    audiences = _align_audiences(user_id)
    user_memories[user_id].append(message)
    audiences.append(audience)


def _drop_last_turn(user_id: str) -> None:
    audiences = _align_audiences(user_id)
    if user_memories.get(user_id):
        user_memories[user_id].pop()
    if audiences:
        audiences.pop()


def _reset_history(user_id: str) -> None:
    user_memories[user_id] = []
    user_memory_audiences[user_id] = []


def _truncate_history(user_id: str) -> None:
    audiences = _align_audiences(user_id)
    if len(user_memories[user_id]) > MAX_HISTORY:
        user_memories[user_id] = user_memories[user_id][-MAX_HISTORY:]
        user_memory_audiences[user_id] = audiences[-MAX_HISTORY:]


def _visible_history(user_id: str, audience: Audience) -> list[dict]:
    """今の聴衆にも見えていた発言だけを返す。"""
    history = user_memories.get(user_id, [])
    audiences = _align_audiences(user_id)
    return [
        message
        for message, recorded in zip(history, audiences)
        if recorded.covers(audience)
    ]


def _session_is_public_only(user_id: str) -> bool:
    """このセッションの全発言が public のノートで交わされたか。

    プロフィール要約は発言内容をそのまま含むため、非公開の会話が
    1 つでも混ざっていれば更新しない。
    """
    return all(audience.visibility == "public" for audience in _align_audiences(user_id))


async def _update_user_profile_in_background(
    user_id: str, user_name: str, history: list, current_profile: str, current_intimacy: int, store: UserStore
) -> None:
    try:
        # 返信直後の連続リクエストによるクォータ超過(429)を避けるため少し待機
        await asyncio.sleep(5)
        analysis = await openrouter.analyze_user_interaction(
            history, current_profile, current_intimacy, user_name
        )
        new_profile = analysis.get("description")
        intimacy_change = analysis.get("intimacy_change", 0)

        if new_profile:
            store.set_profile(user_id, new_profile, user_name)
            logger.info("[%s] プロファイルを更新しました: %s", user_name, new_profile)

        if intimacy_change != 0:
            new_intimacy, applied = store.change_intimacy(user_id, intimacy_change, user_name)
            if applied:
                logger.info(
                    "[%s] 親密度が変化しました: %d (%+d)",
                    user_name,
                    new_intimacy,
                    intimacy_change
                )
            else:
                logger.info(
                    "[%s] 親密度の上昇要求がありましたが、1日1回の制限のため適用されませんでした。(現在: %d)",
                    user_name,
                    new_intimacy
                )
    except Exception:
        logger.error("[%s] プロファイル/親密度更新中にエラーが発生しました", user_name, exc_info=True)


async def run_llm(
    user_id: str,
    user_name: str,
    text: str,
    is_reply: bool = False,
    store: UserStore | None = None,
    image_data_urls: list[str] | None = None,
    has_sensitive_image: bool = False,
    intent_hint: str = "",
    audience: Audience | None = None,
) -> dict:
    """
    botから呼び出されるLLM実行関数。
    ユーザーIDと名前を受け取り、会話履歴を管理し、行動アクションを含む辞書を返す。

    ``audience`` は今回のノートの聴衆。履歴のうち、これより狭い聴衆に
    しか見えていなかった発言は LLM に渡さない。省略された場合は
    聴衆不明として扱い、public 以外の履歴を渡さない（fail-closed）。
    """
    global user_memories, user_locks

    current_audience = audience if audience is not None else _UNKNOWN_AUDIENCE

    # 新規メンション（リプライではない）なら、過去の記憶を消去
    if not is_reply:
        _reset_history(user_id)
        logger.debug("[%s] 新規メンションのため記憶をリセットしました", user_name)

    lock = user_locks.setdefault(user_id, asyncio.Lock())

    async with lock:
        # LLMに「誰からのメッセージか」を意識させるために名前を差し込む
        display_text = text.strip() if text and text.strip() else ""
        if not display_text and image_data_urls:
            display_text = "（画像が送信されました）"

        prompt_with_name = f"[{user_name}さんからのメッセージ]\n{display_text}"
        if image_data_urls:
            prompt_with_name += "\n[画像が添付されています]"
            if has_sensitive_image:
                prompt_with_name += " (注: センシティブ指定されている画像です)"

        # 今回の聴衆にも見えていた履歴だけを使う
        visible_history = _visible_history(user_id, current_audience)

        # ターン数（往復回数）の計算
        history_turns = (len(visible_history) // 2) + 1

        # コスト爆発防止の安全弁（保険: 8往復以上で強制リアクション終了）
        if history_turns > 8:
            logger.info("[%s] 会話ターン数が安全上限(%d)に達したため、リアクションで会話を終了します", user_name, history_turns)
            if store is not None and user_memories[user_id]:
                if _session_is_public_only(user_id):
                    asyncio.create_task(
                        _update_user_profile_in_background(
                            user_id, user_name, list(user_memories[user_id]), "", 0, store
                        )
                    )
                else:
                    logger.info("[%s] 非公開の会話を含むためプロフィール/親密度の更新をスキップします", user_name)
            _reset_history(user_id)
            return {
                "action": "react",
                "reaction": "💤",
                "reply": "",
                "reason": "safety_turn_limit_reached",
            }

        # 履歴にはBase64ではなくテキスト情報のみを保存（トークン肥大化と分析エラーを防ぐ）
        _append_turn(
            user_id,
            {"role": "user", "content": prompt_with_name},
            current_audience,
        )
        messages_for_llm = visible_history + [user_memories[user_id][-1]]

        # ユーザープロフィールと親密度をストアから取得
        user_profile = ""
        intimacy = 0
        if store is not None:
            user_profile = store.get_profile(user_id)
            intimacy = store.get_intimacy(user_id)

        # 会話進行コンテキストの生成
        convo_context = f"現在この相手とのスレッドでのやりとりは {history_turns} ターン目です。"
        if history_turns >= 4:
            convo_context += " 話題が一区切りついている場合は、無理に会話を続けず react（リアクションのみで終了）を選択してフェードアウトしてください。"

        try:
            result = await openrouter.chat_with_history(
                messages_for_llm,
                user_profile=user_profile,
                intimacy=intimacy,
                image_data_urls=image_data_urls,
                convo_context=convo_context,
                intent_hint=intent_hint,
            )

            action = result.get("action", "reply")
            reply_text = result.get("reply", "")

            if action == "reply":
                _append_turn(
                    user_id,
                    {"role": "assistant", "content": reply_text},
                    current_audience,
                )
                # 記憶が上限を超えたら、古いものから忘れる
                _truncate_history(user_id)
            elif action in ("react", "none"):
                # 会話がフェードアウト（終了）したため、会話全体の履歴をもとにプロフィールを1度だけ更新
                if store is not None and user_memories[user_id]:
                    if _session_is_public_only(user_id):
                        asyncio.create_task(
                            _update_user_profile_in_background(
                                user_id, user_name, list(user_memories[user_id]), user_profile, intimacy, store
                            )
                        )
                    else:
                        logger.info("[%s] 非公開の会話を含むためプロフィール/親密度の更新をスキップします", user_name)
                # 会話終了につきメモリをクリア
                _reset_history(user_id)

            return result
        except Exception as e:
            if user_memories.get(user_id):
                _drop_last_turn(user_id)
            return {
                "action": "reply",
                "reaction": "⚠️",
                "reply": f"ごめん、LLMでエラーが起きちゃったみたい…\n`{e}`",
                "reason": "run_llm_exception",
            }
