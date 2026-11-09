import asyncio
import logging

from . import openrouter
from ..stores.user_store import UserStore

logger = logging.getLogger(__name__)

# 記憶を保存する辞書（botが起動している間だけ保持されます）
user_memories: dict = {}
# 各メッセージをどの可視性のノートで交わしたか（user_memories と同じ長さ・同じ順序）
user_memory_visibilities: dict[str, list[str | None]] = {}
# ユーザーごとの排他ロック
user_locks: dict[str, asyncio.Lock] = {}
# 過去何往復分の会話を覚えているか（いまのところ10件＝5往復に制限）
MAX_HISTORY = 10

# 数字が大きいほど、より広い聴衆に公開されるノートだとみなす
_VISIBILITY_RANK = {"specified": 0, "followers": 1, "home": 2, "public": 3}
_DEFAULT_VISIBILITY = "public"


def _normalize_visibility(visibility: str | None) -> str:
    if isinstance(visibility, str):
        normalized = visibility.lower()
        if normalized in _VISIBILITY_RANK:
            return normalized
    return _DEFAULT_VISIBILITY


def _visibility_rank(visibility: str | None) -> int:
    return _VISIBILITY_RANK[_normalize_visibility(visibility)]


def _align_visibilities(user_id: str) -> list[str | None]:
    """履歴の長さに可視性リストを合わせる（直接履歴を差し替えた場合は None で埋める）"""
    history = user_memories.setdefault(user_id, [])
    visibilities = user_memory_visibilities.setdefault(user_id, [])
    if len(visibilities) < len(history):
        visibilities.extend([None] * (len(history) - len(visibilities)))
    elif len(visibilities) > len(history):
        del visibilities[len(history):]
    return visibilities


def _append_history(user_id: str, message: dict, visibility: str | None) -> None:
    visibilities = _align_visibilities(user_id)
    user_memories[user_id].append(message)
    visibilities.append(_normalize_visibility(visibility))


def _pop_history(user_id: str) -> None:
    visibilities = _align_visibilities(user_id)
    if user_memories.get(user_id):
        user_memories[user_id].pop()
    if visibilities:
        visibilities.pop()


def _clear_history(user_id: str) -> None:
    user_memories[user_id] = []
    user_memory_visibilities[user_id] = []


def _truncate_history(user_id: str) -> None:
    visibilities = _align_visibilities(user_id)
    if len(user_memories[user_id]) > MAX_HISTORY:
        user_memories[user_id] = user_memories[user_id][-MAX_HISTORY:]
        user_memory_visibilities[user_id] = visibilities[-MAX_HISTORY:]


def _history_for_visibility(user_id: str, visibility: str | None) -> list[dict]:
    """今回のノートより狭い聴衆にしか見えていなかった発言を除いた履歴を返す

    過去の発言が今回と同じか、それより広い聴衆に公開されていた場合だけ使う。
    たとえば公開ノートへの返信には公開ノートでの発言だけを渡し、
    specified の会話は specified の返信でだけ使う。
    """
    history = user_memories.get(user_id, [])
    visibilities = user_memory_visibilities.get(user_id, [])
    limit = _visibility_rank(visibility)
    selected = []
    for index, message in enumerate(history):
        recorded = visibilities[index] if index < len(visibilities) else None
        if recorded is None or _visibility_rank(recorded) >= limit:
            selected.append(message)
    return selected


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
    visibility: str = "public",
) -> dict:
    """
    botから呼び出されるLLM実行関数。
    ユーザーIDと名前を受け取り、会話履歴を管理し、行動アクションを含む辞書を返す。

    ``visibility`` は今回のノートの可視性。履歴のうち、これより狭い聴衆に
    しか見えていなかった発言は LLM に渡さない。
    """
    global user_memories, user_locks

    # 新規メンション（リプライではない）なら、過去の記憶を消去
    if not is_reply:
        _clear_history(user_id)
        logger.debug("[%s] 新規メンションのため記憶をリセットしました", user_name)

    _align_visibilities(user_id)

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

        # 今回のノートと同じか、より広い聴衆に公開されていた履歴だけを使う
        visible_history = _history_for_visibility(user_id, visibility)

        # ターン数（往復回数）の計算
        history_turns = (len(visible_history) // 2) + 1

        # コスト爆発防止の安全弁（保険: 8往復以上で強制リアクション終了）
        if history_turns > 8:
            logger.info("[%s] 会話ターン数が安全上限(%d)に達したため、リアクションで会話を終了します", user_name, history_turns)
            if store is not None and user_memories[user_id]:
                asyncio.create_task(
                    _update_user_profile_in_background(
                        user_id, user_name, list(user_memories[user_id]), "", 0, store
                    )
                )
            _clear_history(user_id)
            return {
                "action": "react",
                "reaction": "💤",
                "reply": "",
                "reason": "safety_turn_limit_reached",
            }

        # 履歴にはBase64ではなくテキスト情報のみを保存（トークン肥大化と分析エラーを防ぐ）
        _append_history(
            user_id,
            {"role": "user", "content": prompt_with_name},
            visibility,
        )
        messages_for_llm = _history_for_visibility(user_id, visibility)

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
            )

            action = result.get("action", "reply")
            reply_text = result.get("reply", "")

            if action == "reply":
                _append_history(
                    user_id,
                    {"role": "assistant", "content": reply_text},
                    visibility,
                )
                # 記憶が上限を超えたら、古いものから忘れる
                _truncate_history(user_id)
            elif action in ("react", "none"):
                # 会話がフェードアウト（終了）したため、会話全体の履歴をもとにプロフィールを1度だけ更新
                if store is not None and user_memories[user_id]:
                    asyncio.create_task(
                        _update_user_profile_in_background(
                            user_id, user_name, list(user_memories[user_id]), user_profile, intimacy, store
                        )
                    )
                # 会話終了につきメモリをクリア
                _clear_history(user_id)

            return result
        except Exception as e:
            if user_memories.get(user_id):
                _pop_history(user_id)
            return {
                "action": "reply",
                "reaction": "⚠️",
                "reply": f"ごめん、LLMでエラーが起きちゃったみたい…\n`{e}`",
                "reason": "run_llm_exception",
            }
