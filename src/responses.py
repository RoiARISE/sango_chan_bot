import random
from datetime import datetime

SIGNALS = {
    1:  "……まだ寝てないの？ わたしは寝なくてもなんとかなるけど、あなたは違うでしょ…？",
    2:  "こんな時間になっちゃったよ？ さすがに寝ないとダメじゃない……？",
    8:  "おーい、起きる時間だよー、起きて〜",
    9:  "えっと、さすがに起きてるよね…？ あなたがまだ寝てるのなら、わたしも寝ちゃおうかな……？",
    11: "そろそろお昼ごはんのことを考えなくちゃだね。なにを食べようかな……",
    13: "おつかれさま、ご飯は食べた？ じゃあ午後も張り切っていこー",
    14: "ごはんを食べたあとって、眠くなっちゃうよね…。ねむい……",
    15: "ねえねえ、おやつある？ 持ってるならちょうだ〜い……",
    16: "にゃああぁ……",
    18: "んにぃ〜……",
    19: "そろそろお夕飯の時間だね。何が食べたいとか、ある？\n……あ、いや、別に作ってあげるとかじゃ、ないんだけど……",
    22: "お風呂入った？ 歯磨きした？ できてないなら、早めにやってね？",
    23: "えっと、普通なら寝る時間かもしれないけど、あなたはまだ忙しい感じ、なのかな……？ でも、夜ふかしはあんまりしないでね？",
}


TO_YOU_ABUSE = ["変なお願いをするもんだね……", "えっと……、ど、どんな風に罵ってほしいとか、ある？"]


def get_random_response(category: str) -> str:
    """指定されたカテゴリの応答リストからランダムに1つ返す"""
    responses_map = {
        "to_you_abuse": TO_YOU_ABUSE,
    }
    return random.choice(responses_map.get(category, [""]))


def get_current_time_text() -> str:
    """現在時刻を HH:MM:SS 形式で返す"""
    return datetime.now().strftime("%H:%M:%S")


def get_current_time_response() -> str:
    """現在時刻の応答メッセージを生成する"""
    return f'いまは {get_current_time_text()} だよ。どうしたの……？ 時計を見る元気もない感じかな？'


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
