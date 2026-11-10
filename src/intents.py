"""メンション本文から読み取れる意図と、その扱いの対応表。

コマンドごとに定型文を返すのをやめ、キーワードを LLM への「意図のヒント」として
渡す。LLM が無効なときや返信を選ばなかったときは、同じ表の定型文にフォールバックする。
``fixed`` の意図（ping など）は LLM を使わず、常に定型文で即答する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import responses


@dataclass(frozen=True)
class Intent:
    keywords: tuple[str, ...]
    hint: str | Callable[[], str]
    fallback: str | Callable[[str], str]
    fixed: bool = False
    reply_only: bool = False

    def build_hint(self) -> str:
        """LLM に渡す意図の説明を組み立てる"""
        if callable(self.hint):
            return self.hint()
        return self.hint

    def render_fallback(self, display_name: str) -> str:
        """LLM を使えないときの定型文を組み立てる"""
        if callable(self.fallback):
            return self.fallback(display_name)
        return self.fallback


INTENTS: tuple[Intent, ...] = (
    Intent(
        ("はじめまして",),
        "初対面の挨拶をされた。親しみを込めて挨拶を返す",
        "はじめまして、わたしを見つけてくれてありがとう。これからよろしくね",
    ),
    Intent(
        ("こんにちは",),
        "挨拶をされた。自然に挨拶を返す",
        "こんにちは、どうしたの？",
    ),
    Intent(
        ("自己紹介", "あなたは？"),
        "さんご自身の自己紹介を求められている。キャラクター設定に沿って答え、相手のことも聞く",
        "わたしはここ「3.SMbps.net」の看板娘、さんごです。……看板娘は自称だけどね\n"
        "あなたのことも、さんごに教えて欲しいな",
    ),
    Intent(
        ("よしよし", "なでなで"),
        "頭を撫でてほしい、または慰めてほしいと頼まれている。照れながら応じる",
        "わたしの頭なんか撫でて、楽しい？ えっと、あなたが喜んでくれるなら、いいんだけど……",
    ),
    Intent(
        ("にゃーん",),
        "猫の鳴き声で話しかけられた。猫らしく返す",
        "にゃ〜ん",
    ),
    Intent(
        ("罵って",),
        "罵倒してほしいと頼まれている。キャラクターとして軽く罵倒して返す",
        lambda _name: responses.get_random_response("to_you_abuse"),
    ),
    Intent(
        ("さんごちゃん？",),
        "さんごを呼びかけられている。どうしたのか聞く",
        lambda name: f"どうしたの？ {name}さん",
    ),
    Intent(
        ("さんごちゃーん", "さんごちゃ〜ん"),
        "さんごを甘えた調子で呼ばれている。気の抜けた返事をする",
        "は〜い",
    ),
    Intent(
        ("今何時", "いまなんじ"),
        lambda: (
            "現在時刻を聞かれている。"
            f"いまは {responses.get_current_time_text()} です。"
            "この時刻をそのまま使って答えてください"
        ),
        lambda _name: responses.get_current_time_response(),
    ),
    Intent(
        ("ping",),
        "疎通確認をされている。短く返す",
        "pong？",
        fixed=True,
    ),
    Intent(
        ("ちくわ大明神",),
        "「ちくわ大明神」と言われた。意味がわからないので聞き返す",
        "…なに？",
        fixed=True,
        reply_only=True,
    ),
)


def find_intent(text: str) -> Intent | None:
    """本文に含まれる最初の意図を返す。該当がなければ None"""
    for intent in INTENTS:
        if any(keyword in text for keyword in intent.keywords):
            return intent
    return None
