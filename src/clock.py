"""現在時刻の取得を 1 箇所にまとめる。

実行環境のタイムゾーンに従う。コンテナで動かす場合は compose.yml などで TZ を渡す。
"""

from datetime import datetime


def now() -> datetime:
    """ローカルタイムゾーンの現在時刻を、タイムゾーン付きで返す。"""
    return datetime.now().astimezone()


def today() -> str:
    """ローカルタイムゾーンでの日付（YYYY-MM-DD）。"""
    return now().strftime("%Y-%m-%d")
