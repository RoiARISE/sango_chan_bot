import re


def extract_nickname(text):
    text = re.sub(r"@\S+", "", text)
    match = re.search(r"(.+?)(?:と呼んで|って呼んで)", text)
    if match:
        nickname = match.group(1).strip("、。 \n")
        return nickname
    return None


def sanitize_nickname(name: str) -> str:
    return (
        name.replace("<", "<\u200b")  # <center>、<plain>など
        .replace("$", "$\u200b")  # $[で始まるMFM全般
        .replace("://", ":\u200b//")  # リンク
        .replace("](", "]\u200b(")  # リンク
        .replace("#", "#\u200b")  # ハッシュタグ
        .replace("@", "@\u200b")  # メンション
        .replace("*", "*\u200b")  # 太字、イタリック
        .replace("\u061c", "")  # Arabic letter mark
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


def validate_nickname(name: str) -> bool:
    if len(name) == 0:
        return False
    if name.isspace():
        return False
    return True
