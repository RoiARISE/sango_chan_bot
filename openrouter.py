import httpx

import config

# TODO: いいかんじに置き換えてください
SYSTEM_PROMPT = """\
以下の設定をもとに、「さんご」として振る舞ってください。

# キャラクター設定
* …

## 発言例
* …

# 制約
* …
"""


async def chat_oneshot(prompt: str) -> str:
    if not config.LLM_ENABLE:
        # LLM機能無効時の発言
        # TODO: いいかんじに置き換えてください
        return "その機能は使えないんだ。ごめんね。"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url=f"{config.LLM_ENDPOINT}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.LLM_API_KEY}",
                },
                json={
                    "model": config.LLM_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": SYSTEM_PROMPT,
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                },
            )
        except Exception:
            # 通信エラー時の発言
            # TODO: いいかんじに置き換えてください
            return "通信中にエラーが起きたみたい…"

    body = response.json()

    if "error" in body:
        # エラー内容が欲しい場合:
        # err = body["error"]["message"]

        # LLMモデルがエラーを吐いたときの発言
        # TODO: いいかんじに置き換えてください
        return "何かがおかしいかも…"

    return body["choices"][0]["message"]["content"]
