import random
from datetime import datetime

SIGNALS = {
    1:  "……まだ寝てないの？ わたしは寝なくてもなんとかなるけど、あなたは違うでしょ…？",
    2:  "こんな時間になっちゃったよ？ さすがに寝ないとダメじゃない……？",
    8:  "おーい、起きる時間だよー、起きて〜",
    9:  "えっと、さすがに起きてるよね…？ あなたがまだ寝てるのなら、わたしも寝ちゃおうかな……？",
    11: "そろそろお昼ごはんのことを考えなくちゃだね。なにを食べようかな……",
    13: "おつかれさま、ご飯は食べた？ じゃあ午後も張り切っていWこー",
    14: "ごはんを食べたあとって、眠くなっちゃうよね…。ねむい……",
    15: "ねえねえ、おやつある？ 持ってるならちょうだ〜い……",
    16: "にゃああぁ……",
    18: "んにぃ〜……",
    19: "そろそろお夕飯の時間だね。何が食べたいとか、ある？\n……あ、いや、別に作ってあげるとかじゃ、ないんだけど……",
    22: "お風呂入った？ 歯磨きした？ できてないなら、早めにやってね？",
    23: "えっと、普通なら寝る時間かもしれないけど、あなたはまだ忙しい感じ、なのかな……？ でも、夜ふかしはあんまりしないでね？",
}


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

MENTION_SLEEPY = ["よしよし……", "……なでなで、してあげるね"]
TO_YOU_ABUSE = ["変なお願いをするもんだね……", "えっと……、ど、どんな風に罵ってほしいとか、ある？"]
TWO_TIME_SLEEP = [
    "二度寝をするのは悪いことじゃないけど、ほどほどにしておいてね？",
    "30分後にアラームを設定。……よし、準備おっけー。じゃあ、わたしも二度寝しちゃおうかな……",
]


def get_random_response(category: str) -> str:
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


def get_current_time_response() -> str:
    """現在時刻の応答メッセージを生成する"""
    now = datetime.now()
    return f'いまは {now.strftime("%H:%M:%S")} だよ。どうしたの……？ 時計を見る元気もない感じかな？'


def roll_dice(count_str: str, sides_str: str) -> list[int] | None:
    """
    サイコロを振る。
    安全のため、回数や面が多すぎる場合は None を返す。
    """
    try:
        count = int(count_str)
        sides = int(sides_str)
        if count < 1 or sides < 1:
            return None
        if count > 10000 or sides > 10000000000:
            return None
        return [random.randint(1, sides) for _ in range(count)]
    except ValueError:
        return None
