from datetime import datetime
import random

import speedtest


# 元のif文の羅列を、リストからランダムに選ぶ形に変更
GO_WORK = [
    "お仕事、頑張ってきてね。わたし、帰ってくるの、待ってるから……",
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
    "二度寝をするのは悪いことではないけど、ほどほどにしておいてね？",
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


def run_speedtest(result_queue):  # 👈 引数に result_queue を追加
    """
    回線速度を（同期的に）計測し、結果をキューに入れる関数。
    これは重たいので、必ず別スレッドで実行すること。
    """
    try:
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        download_speed = st.download() / 1024 / 1024  # Mbps
        upload_speed = st.upload() / 1024 / 1024  # Mbps
        ping = st.results.ping
        result_str = f"計測かんりょー。下り{download_speed:.2f}Mbps、上り{upload_speed:.2f}Mbps、ping値{ping:.2f}msだったよ。……これは速いって言えるのかな？"
        result_queue.put(result_str)  # 👈 return の代わりに queue.put
    except Exception as e:
        # 👈 エラーもキューに入れる
        error_str = f"ごめん、計測中にエラーが起きちゃったみたい……\n`{e}`"
        result_queue.put(error_str)


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
