from . import openrouter

# 記憶を保存する辞書（botが起動している間だけ保持されます）
user_memories: dict = {}
# 過去何往復分の会話を覚えているか（いまのところ10件＝5往復に制限）
MAX_HISTORY = 10


async def run_llm(user_id: str, user_name: str, text: str, is_reply: bool = False) -> str:
    """
    bot から呼び出されるLLM実行関数。
    ユーザーIDと名前を受け取り、会話履歴を管理する。
    """
    global user_memories

    # 新規メンション（リプライではない）なら、過去の記憶を消去
    if not is_reply:
        user_memories[user_id] = []
        print(f"[{user_name}] 新規メンションのため記憶をリセットしました")

    if user_id not in user_memories:
        user_memories[user_id] = []

    # LLMに「誰からのメッセージか」を意識させるために名前を差し込む
    prompt_with_name = f"[{user_name}さんからのメッセージ]\n{text}"

    user_memories[user_id].append({"role": "user", "content": prompt_with_name})

    # 記憶が上限を超えたら、古いものから忘れる
    if len(user_memories[user_id]) > MAX_HISTORY:
        user_memories[user_id] = user_memories[user_id][-MAX_HISTORY:]

    try:
        result = await openrouter.chat_with_history(user_memories[user_id])
        user_memories[user_id].append({"role": "assistant", "content": result})
        return result
    except Exception as e:
        if user_memories[user_id]:
            user_memories[user_id].pop()
        return f"ごめん、LLMでエラーが起きちゃったみたい…\n`{e}`"
