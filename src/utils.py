import re
from dataclasses import dataclass

# 数字が大きいほど、より広い聴衆に公開されるノートだとみなす
_VISIBILITY_RANK = {"specified": 0, "followers": 1, "home": 2, "public": 3}
UNKNOWN_VISIBILITY = "unknown"


@dataclass(frozen=True)
class Audience:
    """ノートの可視性と、specified のときの宛先集合。

    ``covers(other)`` は「other に見える人は全員 self にも見えるか」を返す。
    会話履歴を今の返信に渡してよいかの判定に使う。
    """

    visibility: str
    recipients: frozenset[str] = frozenset()

    @classmethod
    def from_note(cls, note: dict, my_id: str | None = None) -> "Audience":
        raw = note.get("visibility")
        visibility = raw.lower() if isinstance(raw, str) else UNKNOWN_VISIBILITY
        if visibility not in _VISIBILITY_RANK:
            visibility = UNKNOWN_VISIBILITY

        recipients: frozenset[str] = frozenset()
        if visibility == "specified":
            user_id = note.get("userId") or (note.get("user") or {}).get("id")
            target_ids = set()
            if user_id:
                target_ids.add(user_id)
            for uid in note.get("visibleUserIds") or []:
                target_ids.add(uid)
            if my_id:
                target_ids.discard(my_id)
            if not target_ids and user_id:
                target_ids.add(user_id)
            recipients = frozenset(target_ids)

        return cls(visibility=visibility, recipients=recipients)

    def covers(self, other: "Audience") -> bool:
        if self.visibility == "public":
            # public は全員に見えるので、どの聴衆も包含する
            return True
        if self.visibility in ("home", "followers"):
            # followers / home はどちらも投稿者のフォロワーに見える。
            # specified はフォロワーとは限らないので含めない
            if other.visibility not in _VISIBILITY_RANK:
                return False
            return (
                other.visibility != "specified"
                and _VISIBILITY_RANK[other.visibility] <= _VISIBILITY_RANK[self.visibility]
            )
        if self.visibility == "specified":
            return other.visibility == "specified" and other.recipients <= self.recipients
        # unknown は何も包含しない（fail-closed）
        return False


def extract_nickname(text):
    text = re.sub(r"@\S+", "", text)
    match = re.search(r"(.+?)(?:と呼んで|って呼んで)", text)
    if match:
        nickname = match.group(1).strip("、。 \n")
        if not nickname:
            return None
        return nickname
    return None


def sanitize_nickname(name: str) -> str:
    return (
        name.replace("\u061c", "")  # Arabic letter mark
        .replace("\u200e", "")  # Left-to-right mark
        .replace("\u200f", "")  # Right-to-left mark
        .replace("\u202a", "")  # Left-to-right embedding
        .replace("\u202b", "")  # Right-to-left embedding
        .replace("\u202c", "")  # Pop directional formatting
        .replace("\u202d", "")  # Left-to-right override
        .replace("\u202e", "")  # Right-to-left override
        .replace("\u2066", "")  # Left-to-right isolate
        .replace("\u2067", "")  # Right-to-left isolate
        .replace("\u2068", "")  # First strong isolate
        .replace("\u2069", "")  # Pop directional isolate
        .replace("<", "<\u200b")  # <center>、<plain>など
        .replace("$", "$\u200b")  # $[で始まるMFM全般
        .replace("://", ":\u200b//")  # リンク
        .replace("](", "]\u200b(")  # リンク
        .replace("#", "#\u200b")  # ハッシュタグ
        .replace("@", "@\u200b")  # メンション
        .replace("*", "*\u200b")  # 太字、イタリック
    )


def validate_nickname(name: str) -> bool:
    if len(name) == 0:
        return False
    if name.isspace():
        return False
    return True


def create_mention_string(user: dict) -> str:
    """@username または @username@host 形式のメンション文字列を生成する"""
    username = user.get("username")
    if not username:
        return ""
    host = user.get("host")
    return f"@{username}@{host}" if host else f"@{username}"
