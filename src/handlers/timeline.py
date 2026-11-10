import asyncio
import random

from misskey import Misskey

from ..stores.user_store import UserStore


class TimelineHandler:
    def __init__(self, msk: Misskey, store: UserStore, my_id: str):
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

        # メンション処理は MentionHandler が担当
        if self._my_id in note.get("mentions", []):
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
