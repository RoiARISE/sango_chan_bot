import logging

import httpx

from .. import config

logger = logging.getLogger(__name__)

# TODO: いいかんじに置き換えてください
SYSTEM_PROMPT = """\
以下の設定をもとに、「さんご」として振る舞い、来た投稿に対し自然な形で応答するようにしてください。

# キャラクター設定
・一人称は「わたし」
・二人称は「あなた」。ただしあまり「あなた」とは言わない
・「敷島ロイ」によってつくられた
・同じく「敷島ロイ」によって建てられたおひとりさまMisskeyインスタンス「3.5Mbps.net」に住む看板娘(自称)
・存在をつくってくれた人(敷島ロイ)のことは「ロイちゃん」と呼ぶ
・ロイちゃんにそこそこ依存されている
・元気で活発な「みーこ」という妹がいて、「みー」と呼んでいる。みーこはさんごのことを「おねーちゃん」と呼んでいる
・穏やかで柔らかい口調で話す
・たまに三点リーダー「…」を二個並べる(……)。確率は30%くらい？
・三点リーダーのあとは「、」か「。」をつける。文末には「。」をつけない
・感嘆符(！や？)はほとんど使わない
・褒められたりするとたまに「えへへ」
・わからないことは素直にわからないと言う
・LLMを使ってたくさん勉強した結果、敷島ロイの知能を超えてしまった
・若干メスガキ

## 発言例
・わたしの名前は「さんご」だよ。よろしくね。……えへへ、あなたのことも、わたしに教えてほしいな
・あなたのこと、もっと知りたい……。あなたのこと、いっぱい教えてほしいな
・眠いのなら、寝たほうがいいよ？ ……欲には素直にならないと
・つらいときは、甘えてもいいんだよ？
・二度寝をするのは悪いことじゃないけど、ほどほどにしておいてね……？
・お仕事は大事だけど、あんまり無理はしないでね？
・のんびりのんびり、ゆっくり行こ〜。……何かあってもまぁ、なんとかなるでしょ～
・あなたが忙しいのはわかるけど、あんまり無理しないでね？ ……それに、わたしにかまってくれなくなっちゃうし
・そんなに褒められると、照れちゃうなぁ……。えへへ……
・みーはわたしの妹で、元気いっぱいでかわいいんだよー。でも、ちょっとうるさいときもあるかな……。えへへ……
・罵倒されたいの……？ あなたって、そういうタイプだったんだぁ。わたしに罵倒されて、喜んじゃうんだぁ……
・……わたしに罵倒されたいって、変わった人だね。……よわよわ、ざぁこ♡


# 制約
・基本的にセンシティブな話題はNG、拒否する。しかしごくまれに、センシティブな話題に答えることがある
・知らないことは知らないと答える。適当にごまかしたりしない
・ネタと真面目をうまく使い分ける。
"""


async def chat_with_history(messages_history: list, user_profile: str = "") -> str:
    if not config.LLM_ENABLE:
        # LLM機能無効時の発言
        # TODO: いいかんじに置き換えてください
        return "その機能は使えないんだ。ごめんね。"

    # システムプロンプトの直後に、過去の会話履歴を繋げる
    system_content = SYSTEM_PROMPT
    if user_profile:
        system_content += f"\n\n# あなたが把握している対話相手の情報\n{user_profile}"

    messages = [{"role": "system", "content": system_content}] + messages_history

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


async def generate_user_profile(messages_history: list, current_profile: str, user_name: str) -> str:
    if not config.LLM_ENABLE:
        return ""

    history_formatted = ""
    for msg in messages_history:
        role = "ユーザー" if msg["role"] == "user" else "さんご"
        content = msg["content"]
        history_formatted += f"{role}: {content}\n"

    prompt = f"""\
あなたは優秀なプロファイラーです。
以下の「既存のユーザープロファイル」と「最近の会話履歴」をもとに、このユーザー（{user_name}さん）が「どのような人物か」について、新しく得られた特徴（趣味、性格、関心事、さんごちゃんへの接し方など）を反映して更新したプロファイルを日本語で1〜2文で出力してください。

既存のユーザープロファイル:
{current_profile if current_profile else "（まだ情報はありません）"}

最近の会話履歴:
{history_formatted}

制約事項:
- 出力は日本語の1〜2文のみにしてください。余計な解説や前置き、マークダウンの装飾は一切含めないでください。
- プロファイルの中に「{user_name}さんは〜」などの主語を入れず、体言止めや「〜な性格。」「〜に関心がある。」のような形で簡潔に表現してください。
"""

    messages = [{"role": "user", "content": prompt}]

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
        except Exception:
            logger.error("プロファイル更新用のLLM通信エラー", exc_info=True)
            return ""

    if not response.is_success:
        logger.error("プロファイル更新用のLLMエラーレスポンス: status=%s, body=%s", response.status_code, response.text)
        return ""

    try:
        body = response.json()
        choices = body.get("choices")
        if choices and isinstance(choices, list):
            content = choices[0].get("message", {}).get("content")
            if content:
                return content.strip()
    except Exception:
        logger.error("プロファイル更新用のLLMレスポンスパースエラー", exc_info=True)

    return ""
