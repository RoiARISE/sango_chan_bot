import httpx

from .. import config

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
        except httpx.TimeoutException as e:
            print(f"LLM通信タイムアウト: endpoint={config.LLM_ENDPOINT}, model={config.LLM_MODEL}, error={e}")
            # 通信エラー時の発言
            # TODO: いいかんじに置き換えてください
            return "通信中にエラーが起きたみたい…"
        except httpx.RequestError as e:
            print(f"LLM通信エラー: endpoint={config.LLM_ENDPOINT}, model={config.LLM_MODEL}, error={e}")
            # 通信エラー時の発言
            # TODO: いいかんじに置き換えてください
            return "通信中にエラーが起きたみたい…"
        except Exception as e:
            print(f"LLM予期せぬエラー: endpoint={config.LLM_ENDPOINT}, model={config.LLM_MODEL}, error={e}")
            return "通信中にエラーが起きたみたい…"

    if not response.is_success:
        print(f"LLMエラーレスポンス: status={response.status_code}, body={response.text}")
        # LLMモデルがエラーを吐いたときの発言
        # TODO: いいかんじに置き換えてください
        return "何かがおかしいかも…"

    try:
        body = response.json()
    except Exception as e:
        print(f"LLMレスポンスのJSONパースエラー: {e}, raw={response.text}")
        return "何かがおかしいかも…"

    if "error" in body:
        print(f"LLMエラー: {body['error']}")
        # LLMモデルがエラーを吐いたときの発言
        # TODO: いいかんじに置き換えてください
        return "何かがおかしいかも…"

    choices = body.get("choices")
    if not choices or not isinstance(choices, list):
        print(f"LLMレスポンスに choices がありません: {body}")
        return "何かがおかしいかも…"

    message = choices[0].get("message", {})
    content = message.get("content")
    if content is None:
        print(f"LLMレスポンスに content がありません: {body}")
        return "何かがおかしいかも…"

    return content
