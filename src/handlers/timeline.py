import asyncio
import random
from typing import Callable

from misskey import Misskey

from .. import responses
from ..stores.nickname_store import NicknameStore
from ..utils import create_mention_string


class TimelineHandler:
    def __init__(self, msk: Misskey, store: NicknameStore, my_id: str):
        self._msk = msk
        self._store = store
        self._my_id = my_id

    async def handle(self, note: dict) -> None:
        """ホームタイムラインのノートに対する処理 (homeTimeline)"""
        if not note.get("text") or note.get("renoteId") or note["user"]["id"] == self._my_id:
            return

        text = note["text"]
        user = note["user"]
        user_id = user["id"]
        vis = note.get("visibility", "public")
        is_reply = note.get("replyId") is not None
        CHARS_TO_STRIP = " 　\n\t。、？！?!"

        # メンション処理は MentionHandler が担当
        if self._my_id in note.get("mentions", []):
            return

        cleaned_text = text.strip(CHARS_TO_STRIP)
        CONTEXT_LIMIT = 10

        timeline_keywords: list[tuple[tuple[str, ...], str | Callable[[], str], bool | None, str]] = [
            # ( (キーワード,), "応答", リプライ制限, 一致モード )

            # --- "exact" (完全一致) ---
            (("おはよ",), f"おはよ、よく眠れた？ わたしは{responses.get_random_response('morning')}", False, "exact"),
            (("おそよ",), "遅いよ、ねぼすけさん。なんで寝坊したのか、ちゃんと説明して？", False, "exact"),
            (("二度寝",), responses.get_random_response("two_time_sleep"), False, "exact"),
            (("にゃーん",), "にゃーん。……えへへ、わたしも混ぜて？", False, "exact"),
            (("ぬるぽ",), ":galtu:", None, "exact"),

            # --- "partial" (部分一致) ---
            (("出勤",), responses.get_random_response("go_work"), None, "partial"),
            (("退勤", "しごおわ"), "お仕事終わったの？ お疲れさま～。 ……わたしの癒し、必要かな？ 必要なら、いつでも言ってね", None, "partial"),

            # --- "context" (前後n文字まで許容) ---
            (("疲れた", "つかれた", "疲れてる", "つかれてる", "疲れている", "つかれている"), "ひとやすみ、する？ それとも、わたしが癒してあげよっか？", None, "partial"),
            (("眠い", "眠たい", "ねむ"), "なるほど、眠いんだね。……我慢はよくないよ？ 欲には素直にならないと", False, "context"),
            (("つらい", "つらすぎ"), "つらいときは、甘えてもいいんだよ？", None, "context"),
            (("おやすみ",), responses.get_random_response("good_night"), False, "context"),
        ]

        for keywords, response, reply_rule, match_mode in timeline_keywords:
            if reply_rule is not None:
                if reply_rule is True and not is_reply:
                    continue
                if reply_rule is False and is_reply:
                    continue

            matched = False

            if match_mode == "exact":
                if cleaned_text in keywords:
                    matched = True

            elif match_mode == "partial":
                if any(kw in text for kw in keywords):
                    matched = True

            elif match_mode == "context":
                for kw in keywords:
                    if kw in text:
                        parts = text.split(kw, 1)
                        before = parts[0].strip(CHARS_TO_STRIP)
                        after = parts[1].strip(CHARS_TO_STRIP)
                        if len(before) <= CONTEXT_LIMIT and len(after) <= CONTEXT_LIMIT:
                            matched = True
                            if keywords == ("眠い", "眠たい", "ねむ") and "くない" in after:
                                matched = False
                            if matched:
                                break

            if matched:
                if keywords == ("にゃーん",) and random.randint(1, 2) != 1:
                    continue
                if keywords == ("ぬるぽ",) and random.randint(1, 3) != 1:
                    continue
                if callable(response):
                    response = response()
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text=response,
                    reply_id=note["id"],
                    visibility=vis
                )
                if response == ":galtu:":
                    await asyncio.to_thread(
                        self._msk.notes_reactions_create,
                        note_id=note["id"],
                        reaction=response
                    )
                return

        if "さんごちゃん" in text:
            if random.randint(1, 3) == 1:
                parts = text.split("さんごちゃん", 1)
                before = parts[0].strip()
                after = parts[1].strip()
                if before or after:
                    name = self._store.get_display_name(user_id, user)
                    await asyncio.to_thread(
                        self._msk.notes_create,
                        text=f"呼んだ？ {name}さん",
                        reply_id=note["id"],
                        visibility=vis
                    )
