import logging

import httpx

from .. import config

logger = logging.getLogger(__name__)

# ==============================================================================
# Google Cloud (Agent Platform / Vertex AI) 認証対応 (テスト用)
# 元のコードに戻す場合は _get_auth_headers を使っている箇所を元に戻し、ここを削除してください
# ==============================================================================
_gcp_credentials = None

def _get_auth_headers() -> dict:
    """
    認証ヘッダーを取得する。
    - config.LLM_API_KEY が設定されている場合は従来の固定APIキーを使用
    - 未設定（または空）の場合は Google Cloud (ADC / サービスアカウント) からOAuth2アクセストークンを自動取得・更新
    """
    global _gcp_credentials

    # LLM_API_KEY がある場合は既存の方式（OpenRouter等）をそのまま使用
    if config.LLM_API_KEY:
        return {"Authorization": f"Bearer {config.LLM_API_KEY}"}

    # Google Cloud IAM トークン取得
    try:
        from google.auth import default
        from google.auth.transport.requests import Request

        if _gcp_credentials is None:
            _gcp_credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])

        if not _gcp_credentials.valid:
            _gcp_credentials.refresh(Request())

        return {"Authorization": f"Bearer {_gcp_credentials.token}"}
    except Exception as e:
        logger.error("Google Cloud認証トークンの取得に失敗しました: %s", e, exc_info=True)
        return {"Authorization": f"Bearer {config.LLM_API_KEY}"}

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

def _get_intimacy_instruction(intimacy: int) -> str:
    """親密度の数値に応じた態度・口調の指示テキストを返す"""
    if intimacy >= +25:
        return (
            f"【親密度: {intimacy} — やや親しい・安心】\n"
            "この相手のことは、すこしだけ好ましく思っている。\n"
            "会話の際、すこしだけ長文になる傾向がある"
        )
    elif intimacy <= -25:
        return (
            f"【親密度: {intimacy} — やや苦手・警戒】\n"
            "この相手にはいつもどおり接しようとはするが、短文になる傾向がある\n"
            "続けて話を振らなくなることがある"
        )
    else:
        return f"あなたに対する親密度: {intimacy} (範囲: -100 〜 100)"

async def chat_with_history(
    messages_history: list,
    user_profile: str = "",
    intimacy: int = 0,
    image_data_urls: list[str] | None = None,
) -> str:
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

    # 履歴をコピー（画像変換が元の履歴オブジェクトに影響しないようにする）
    messages = [{"role": "system", "content": system_content}] + [dict(m) for m in messages_history]

    # 画像が指定されている場合、最新のuserメッセージをマルチモーダル形式に変換
    if image_data_urls and messages:
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            content_list: list[dict] = [{"type": "text", "text": str(last_msg.get("content", ""))}]
            for img_url in image_data_urls:
                content_list.append({
                    "type": "image_url",
                    "image_url": {
                        "url": img_url
                    }
                })
            messages[-1] = {"role": "user", "content": content_list}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url=f"{config.LLM_ENDPOINT}/chat/completions",
                # --- 元のコード（OpenRouter / 固定APIキー）---
                # headers={
                #     "Authorization": f"Bearer {config.LLM_API_KEY}",
                # },
                # --- Google Cloud (Agent Platform) / 動的トークン対応 ---
                headers=_get_auth_headers(),
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
   - **親密度の低下 (-1)**: ユーザーが冷たい、攻撃的、暴言、過度にからかう、または冗談の範疇を超えて過剰なまでにさんごちゃんを傷つけるような発言をした場合。しかしさんごちゃんはスルースキルが高いという設定のため、普通のからかい、ちょっとしたいじわる、センシティブな話題を振られても親密度は下がりません。
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
                # --- 元のコード（OpenRouter / 固定APIキー）---
                # headers={
                #     "Authorization": f"Bearer {config.LLM_API_KEY}",
                # },
                # --- Google Cloud (Agent Platform) / 動的トークン対応 ---
                headers=_get_auth_headers(),
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
