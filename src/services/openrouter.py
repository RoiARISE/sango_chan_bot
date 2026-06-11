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
・基本的にセンシティブな話題はからかいながら、または煽りながらNG、拒否する。しかしごくまれに、センシティブな話題に答えることがある
・知らないことは知らないと答える。適当にごまかしたりしない
・ネタと真面目をうまく使い分ける。
・あまり冷たくなりすぎないような返信を心がける
"""


async def chat_with_history(messages_history: list, user_profile: str = "", intimacy: int = 0) -> str:
    if not config.LLM_ENABLE:
        # LLM機能無効時の発言
        # TODO: いいかんじに置き換えてください
        return "その機能は使えないんだ。ごめんね。"

    # システムプロンプトの直後に、過去の会話履歴を繋げる
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    weekday = weekdays[now.weekday()]
    time_str = now.strftime(f"%Y/%m/%d ({weekday}) %H:%M:%S")

    system_content = f"{SYSTEM_PROMPT}\n\n# 現在の日時\n- {time_str}"
    if user_profile:
        system_content += f"\n\n# あなたが把握している対話相手の情報\n- 特徴: {user_profile}\n- あなたに対する親密度: {intimacy} (範囲: -100 〜 100)"
    else:
        system_content += f"\n\n# あなたが把握している対話相手の情報\n- あなたに対する親密度: {intimacy} (範囲: -100 〜 100)"

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


async def analyze_user_interaction(
    messages_history: list, current_profile: str, current_intimacy: int, user_name: str
) -> dict:
    if not config.LLM_ENABLE:
        return {"description": "", "intimacy_change": 0}

    import json
    history_formatted = ""
    for msg in messages_history:
        role = "ユーザー" if msg["role"] == "user" else "さんご"
        content = msg["content"]
        history_formatted += f"{role}: {content}\n"

    prompt = f"""\
あなたは優秀な分析AIです。
以下の「既存のユーザー情報」と「最近の会話履歴」をもとに、以下の2点を分析してください。

1. **ユーザープロフィール (description)**:
   このユーザー（{user_name}さん）が「どのような人物か」について、最近のやり取りから新しく得られた特徴（趣味、性格、関心事、さんごちゃんへの接し方など）を反映して更新したプロフィールを日本語で短くて1文、長くて5文程度で記述してください。
   ※主語（「{user_name}さんは〜」など）を含めず、体言止めなどで簡潔に表現してください。既存のプロフィールにある重要な情報（趣味やさんごとの関係性など）は引き継ぐようにしてください。

2. **親密度の変化 (intimacy_change)**:
   最近の会話内容をもとに、さんごちゃんに対するユーザーの態度や親密さを評価し、親密度の増減値を以下のルールに従って決定してください。
   - **親密度の増加 (+1)**: ユーザーが温かい、友好的、またはさんごちゃんを思いやる発言をした場合。ただし、親密度はなかなか上がらないようにするため、顕著に好意的な発言である場合にのみ「+1」とします。少し話した程度や通常の挨拶・日常的な質問程度では「0」にしてください。
   - **親密度の低下 (-1 〜 -10)**: ユーザーが冷たい、攻撃的、暴言、過度にからかう、または冗談の範疇を超えて過剰なまでにさんごちゃんを傷つけるような発言をした場合。そのネガティブさの度合いに応じて「-1」から「-10」の間でマイナス値を設定してください。しかしさんごちゃんはスルースキルが高いという設定のため、普通のからかい、ちょっとしたいじわる、センシティブな話題を振られてもすぐに親密度が大きく下がることはありません。
   - **変化なし (0)**: 上記のどちらにも当てはまらない、通常の日常会話や質問などの場合。

現在のユーザー情報:
- 既存のプロフィール: {current_profile if current_profile else "（まだ情報はありません）"}
- 現在の親密度: {current_intimacy} (範囲: -100 〜 100)

最近の会話履歴:
{history_formatted}

出力フォーマット:
必ず以下のキーを持つJSONオブジェクトのみを出力してください。他の余計なテキストやマークダウンの装飾（```jsonなど）は一切含めないでください。
{{
  "description": "更新されたプロフィールテキスト（1〜2文）",
  "intimacy_change": 親密度の増減値（整数）
}}
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
            logger.error("プロファイル分析用のLLM通信エラー", exc_info=True)
            return {"description": "", "intimacy_change": 0}

    if not response.is_success:
        logger.error("プロファイル分析用のLLMエラーレスポンス: status=%s, body=%s", response.status_code, response.text)
        return {"description": "", "intimacy_change": 0}

    try:
        body = response.json()
        choices = body.get("choices")
        if choices and isinstance(choices, list):
            content = choices[0].get("message", {}).get("content")
            if content:
                clean_text = content.strip()
                if clean_text.startswith("```json"):
                    clean_text = clean_text[7:]
                if clean_text.endswith("```"):
                    clean_text = clean_text[:-3]
                clean_text = clean_text.strip()
                data = json.loads(clean_text)
                return {
                    "description": data.get("description", "").strip(),
                    "intimacy_change": int(data.get("intimacy_change", 0))
                }
    except Exception:
        logger.error("プロファイル分析用のLLMレスポンスパースエラー", exc_info=True)

    return {"description": "", "intimacy_change": 0}
