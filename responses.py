from asyncio import to_thread
from datetime import datetime
import random

import speedtest

import openrouter


# 元のif文の羅列を、リストからランダムに選ぶ形に変更
GO_WORK = [
    "お仕事、頑張ってきてね。わたし、あなたが帰ってくるの、待ってるから……",
    "お仕事は大事だけど、あんまり無理はしないでね？",
    "お仕事とわたし、どっちが大事なんだろう……。まぁ、わたしにはロイちゃんがいるから、いい……のかな？\n……あっ、ち、違う！ これは違くて…！ なんでもないから……！",
]

GOOD_NIGHT = [
    "また朝に会おうね、おやすみ",
    "おやすみって言ったんだから、夜更かししようなんて考えないでね？",
    "寝ちゃうんだ……。ふーん……",
]

MORNING = [
    "よく眠れたよ～。元気いーっぱい",
    "あんまり寝れなかったかな……。まぁ、なんとかなるでしょ～",
]

# 他の応答も同様にリスト化...
# 例
MENTION_SLEEPY = ["よしよし……", "……なでなで、してあげるね"]
TO_YOU_ABUSE = ["変なお願いをするもんだね……", "えっと……、ど、どんな風に罵ってほしいとか、ある？"]
TWO_TIME_SLEEP = [
    "二度寝をするのは悪いことじゃないけど、ほどほどにしておいてね？",
    "30分後にアラームを設定。……よし、準備おっけー。じゃあ、わたしも二度寝しちゃおうかな……",
]


def get_random_response(category):
    """指定されたカテゴリの応答リストからランダムに1つ返す"""
    responses_map = {
        "go_work": GO_WORK,
        "good_night": GOOD_NIGHT,
        "morning": MORNING,
        "mention_sleepy": MENTION_SLEEPY,
        "to_you_abuse": TO_YOU_ABUSE,
        "two_time_sleep": TWO_TIME_SLEEP,
    }
    return random.choice(responses_map.get(category, [""]))


def get_current_time_response():
    """現在時刻の応答メッセージを生成する"""
    now = datetime.now()
    # f'{now.minute:02}' のように :02 をつけると、1桁の数字が 01, 02 のように表示されます
    return f'いまは {now.hour}:{now.minute:02}:{now.second:02} だよ。どうしたの……？ 時計を見る元気もない感じかな？'


async def run_speedtest():
    """
    回線速度を計測する非同期関数
    """
    try:
        st = speedtest.Speedtest(secure=True)
        await to_thread(st.get_best_server)
        download_speed = await to_thread(st.download) / 1024 / 1024  # Mbps
        upload_speed = await to_thread(st.upload) / 1024 / 1024  # Mbps
        ping = st.results.ping
        result_str = f"計測かんりょー。下り{download_speed:.2f}Mbps、上り{upload_speed:.2f}Mbps、ping値{ping:.2f}msだったよ。……これは速いって言えるのかな？"
        return result_str
    except Exception as e:
        # 👈 エラーもキューに入れる
        error_str = f"ごめん、計測中にエラーが起きちゃったみたい……\n`{e}`"
        return error_str


def roll_dice(count_str, sides_str):
    """
    サイコロを振る。
    安全のため、回数や面が多すぎる場合は None を返す。
    """
    try:
        count = int(count_str)
        sides = int(sides_str)
        # 0個や0面は振れない
        if count < 1 or sides < 1:
            return None
        # 悪用を防ぐための上限設定
        if count > 10000 or sides > 10000000000:
            return None
        # リスト内包表記でサイコロを振る
        rolls = [random.randint(1, sides) for _ in range(count)]
        return rolls
    except ValueError:
        # 数字が大きすぎるなどでint()に失敗した場合
        return None

async def _async_llm_request(text: str):
    """内部専用の LLM 呼び出し"""
    return await openrouter.chat_oneshot(text)


# 記憶を保存する辞書（botが起動している間だけ保持されます）
user_memories = {}
# 過去何往復分の会話を覚えているか（いまのところ10件＝5往復に制限）
MAX_HISTORY = 10

async def _async_llm_request(messages_history: list):
    """内部専用の LLM 呼び出し（履歴対応版）"""
    return await openrouter.chat_with_history(messages_history)


async def run_llm(user_id: str, user_name: str, text: str, is_reply: bool = False):
    """
    bot.py から呼び出されるLLM実行関数
    ユーザーIDと名前を受け取り、記憶を管理します。
    """
    global user_memories

    # ★追加部分：新規メンション（リプライではない）なら、過去の記憶を消去
    if not is_reply:
        user_memories[user_id] = []
        print(f"[{user_name}] 新規メンションのため記憶をリセットしました")

    # 初めて話しかけてきた人の場合は、空の履歴リストを作る
    if user_id not in user_memories:
        user_memories[user_id] = []

    # LLMに「誰からのメッセージか」を意識させるために、こっそり名前を差し込みます
    prompt_with_name = f"[{user_name}さんからのメッセージ]\n{text}"

    # ユーザーの今回の発言を記憶に追加
    user_memories[user_id].append({"role": "user", "content": prompt_with_name})

    # 記憶が上限を超えたら、古いものから忘れる
    if len(user_memories[user_id]) > MAX_HISTORY:
        user_memories[user_id] = user_memories[user_id][-MAX_HISTORY:]

    try:
        # 履歴を丸ごとLLMに投げる
        result = await _async_llm_request(user_memories[user_id])

        # LLMの返答も記憶に追加する
        user_memories[user_id].append({"role": "assistant", "content": result})

        return result
    except Exception as e:
        # エラーが起きたら、今回の記憶を一旦消してあげる（リトライできるように）
        if user_memories[user_id]:
            user_memories[user_id].pop()
        return f"ごめん、LLMでエラーが起きちゃったみたい…\n`{e}`"