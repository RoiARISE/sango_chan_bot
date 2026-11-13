import re
from dataclasses import dataclass

# ノートを閲覧できる人の範囲。home は「グローバルタイムラインに流すか」の
# 違いで、閲覧できる人は public と同じなので可視性の段階には含めない。
_KNOWN_VISIBILITIES = {"public", "home", "followers", "specified"}
UNKNOWN_VISIBILITY = "unknown"


@dataclass(frozen=True)
class Audience:
    """ノートの閲覧範囲と、specified のときの宛先集合。

    ``covers(other)`` は「other に見える人は全員 self にも見えるか」を返す。
    会話履歴を今の返信に渡してよいかの判定に使う。

    home はタイムラインへの配信範囲の違いで、閲覧できる人は public と同じ。
    """

    visibility: str
    recipients: frozenset[str] = frozenset()

    @classmethod
    def from_note(cls, note: dict, my_id: str | None = None) -> "Audience":
        raw = note.get("visibility")
        visibility = raw.lower() if isinstance(raw, str) else UNKNOWN_VISIBILITY
        if visibility not in _KNOWN_VISIBILITIES:
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

    @property
    def is_public(self) -> bool:
        """誰でも閲覧できるノートか。

        home は配信範囲だけの違いなので public と同じく全員が閲覧できる。
        """
        return self.visibility in ("public", "home")

    def covers(self, other: "Audience") -> bool:
        if self.is_public:
            # public / home は誰でも見られるので、どの聴衆も包含する
            return True
        if self.visibility == "followers":
            # followers は投稿者のフォロワーだけ。フォロワーかどうか分からない
            # specified は含めない
            return other.visibility == "followers"
        if self.visibility == "specified":
            return other.visibility == "specified" and other.recipients <= self.recipients
        # unknown は何も包含しない（fail-closed）
        return False


def reply_audience(note: dict) -> tuple[str, list[str] | None]:
    """返信に使う可視性と、明示的な宛先を返す。

    Misskey の ``followers`` は「そのノートの投稿者のフォロワー」基準。
    bot が同じ値で返信すると、返信は bot のフォロワーに見えてしまうため、
    投稿者だけへの ``specified`` に落とす。``home`` は配信範囲の違いで
    閲覧範囲は ``public`` と同じなので、そのまま返す。
    """
    visibility = note.get("visibility", "public")
    if not isinstance(visibility, str) or visibility.lower() != "followers":
        return visibility, None
    author_id = note.get("userId") or (note.get("user") or {}).get("id")
    return "specified", [author_id] if author_id else []


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
    # 双方向制御文字は除去する。
    name = (
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
    )
    # 1文字のMFM開始子は、すでに ZWSP が続いている場合は二重に挿入しない。
    # 読み出し時にも安全に再適用できるよう、この関数は冪等にする。
    name = re.sub(r"<(?!\u200b)", "<\u200b", name)  # <center>、<plain>など
    name = re.sub(r"\$(?!\u200b)", "$\u200b", name)  # $[で始まるMFM全般
    name = name.replace("://", ":\u200b//")  # リンク
    name = name.replace("](", "]\u200b(")  # リンク
    name = re.sub(r"#(?!\u200b)", "#\u200b", name)  # ハッシュタグ
    name = re.sub(r"@(?!\u200b)", "@\u200b", name)  # メンション
    name = re.sub(r"\*(?!\u200b)", "*\u200b", name)  # 太字、イタリック
    return name


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
