import logging

import httpx

from .. import config

logger = logging.getLogger(__name__)

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


async def chat_with_history(messages_history: list) -> str:
    if not config.LLM_ENABLE:
        # LLM機能無効時の発言
        # TODO: いいかんじに置き換えてください
        return "その機能は使えないんだ。ごめんね。"

    # システムプロンプトの直後に、過去の会話履歴を繋げる
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages_history

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url=f"{config.LLM_ENDPOINT}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.LLM_API_KEY}",
                },
                json={
                    "model": config.LLM_MODEL,
                    "messages": messages,
                },
                timeout=30.0,
            )
        except httpx.TimeoutException:
            logger.error("LLM通信タイムアウト: endpoint=%s, model=%s", config.LLM_ENDPOINT, config.LLM_MODEL, exc_info=True)
            # 通信エラー時の発言
            # TODO: いいかんじに置き換えてください
            return "通信中にエラーが起きたみたい…"
        except httpx.RequestError:
            logger.error("LLM通信エラー: endpoint=%s, model=%s", config.LLM_ENDPOINT, config.LLM_MODEL, exc_info=True)
            # 通信エラー時の発言
            # TODO: いいかんじに置き換えてください
            return "通信中にエラーが起きたみたい…"
        except Exception:
            logger.error("LLM予期せぬエラー: endpoint=%s, model=%s", config.LLM_ENDPOINT, config.LLM_MODEL, exc_info=True)
            return "通信中にエラーが起きたみたい…"

    if not response.is_success:
        logger.error("LLMエラーレスポンス: status=%s, body=%s", response.status_code, response.text)
        # LLMモデルがエラーを吐いたときの発言
        # TODO: いいかんじに置き換えてください
        return "何かがおかしいかも…"

    try:
        body = response.json()
    except Exception:
        logger.error("LLMレスポンスのJSONパースエラー: raw=%s", response.text, exc_info=True)
        return "何かがおかしいかも…"

    if "error" in body:
        logger.error("LLMエラー: %s", body["error"])
        # LLMモデルがエラーを吐いたときの発言
        # TODO: いいかんじに置き換えてください
        return "何かがおかしいかも…"

    choices = body.get("choices")
    if not choices or not isinstance(choices, list):
        logger.error("LLMレスポンスに choices がありません: %s", body)
        return "何かがおかしいかも…"

    message = choices[0].get("message", {})
    content = message.get("content")
    if content is None:
        logger.error("LLMレスポンスに content がありません: %s", body)
        return "何かがおかしいかも…"

    return content
