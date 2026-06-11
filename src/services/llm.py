import asyncio
import logging

from . import openrouter
from ..stores.user_store import UserStore

logger = logging.getLogger(__name__)

# 記憶を保存する辞書（botが起動している間だけ保持されます）
user_memories: dict = {}
# ユーザーごとの排他ロック
user_locks: dict[str, asyncio.Lock] = {}
# 過去何往復分の会話を覚えているか（いまのところ10件＝5往復に制限）
MAX_HISTORY = 10


async def _update_user_profile_in_background(
    user_id: str, user_name: str, history: list, current_profile: str, current_intimacy: int, store: UserStore
) -> None:
    try:
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
    user_id: str, user_name: str, text: str, is_reply: bool = False, store: UserStore | None = None
) -> str:
    """
    botから呼び出されるLLM実行関数。
    ユーザーIDと名前を受け取り、会話履歴を管理する。
    """
    global user_memories, user_locks

    # 新規メンション（リプライではない）なら、過去の記憶を消去
    if not is_reply:
        user_memories[user_id] = []
        logger.debug("[%s] 新規メンションのため記憶をリセットしました", user_name)

    if user_id not in user_memories:
        user_memories[user_id] = []

    lock = user_locks.setdefault(user_id, asyncio.Lock())

    async with lock:
        # LLMに「誰からのメッセージか」を意識させるために名前を差し込む
        prompt_with_name = f"[{user_name}さんからのメッセージ]\n{text}"
        user_memories[user_id].append({"role": "user", "content": prompt_with_name})

        # ユーザープロフィールと親密度をストアから取得
        user_profile = ""
        intimacy = 0
        if store is not None:
            user_profile = store.get_profile(user_id)
            intimacy = store.get_intimacy(user_id)

        try:
            result = await openrouter.chat_with_history(
                user_memories[user_id], user_profile=user_profile, intimacy=intimacy
            )
            user_memories[user_id].append({"role": "assistant", "content": result})
            # 記憶が上限を超えたら、古いものから忘れる
            if len(user_memories[user_id]) > MAX_HISTORY:
                user_memories[user_id] = user_memories[user_id][-MAX_HISTORY:]

            # バックグラウンドでプロフィール/親密度更新タスクを実行
            if store is not None:
                asyncio.create_task(
                    _update_user_profile_in_background(
                        user_id, user_name, list(user_memories[user_id]), user_profile, intimacy, store
                    )
                )

            return result
        except Exception as e:
            if user_memories[user_id]:
                user_memories[user_id].pop()
            return f"ごめん、LLMでエラーが起きちゃったみたい…\n`{e}`"
