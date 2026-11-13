import asyncio
import logging
import random
import re
from time import monotonic

from misskey import Misskey

from ..stores.user_store import UserStore
from ..utils import reply_audience

logger = logging.getLogger(__name__)

# nobot 判定のキャッシュ有効期間（秒）
NOBOT_CACHE_TTL = 600.0

# プロフィール中の #nobot ハッシュタグ（全角＃・大文字小文字も許容）
# MFM のハッシュタグは空白・改行と `.,!?'"#:/【】<>`、閉じ括弧で終端する。
# 日本語などはタグの一部になるため、#nobotです は #nobot とは別のタグになる。
# 開き括弧は対になる場合だけタグに含まれるので、保守的に終端扱いしない。
NOBOT_HASHTAG_RE = re.compile(
    r"(?<![A-Za-z0-9])[#＃]nobot(?=$|[\s.,!?'\"#:/【】<>\]\)」）])",
    re.IGNORECASE,
)


class TimelineHandler:
    def __init__(self, msk: Misskey, store: UserStore, my_id: str):
        self._msk = msk
        self._store = store
        self._my_id = my_id
        # user_id -> (判定時刻, nobot かどうか)
        self._nobot_cache: dict[str, tuple[float, bool]] = {}

    async def _is_nobot(self, user: dict) -> bool:
        """プロフィールに #nobot ハッシュタグが含まれるユーザーかどうかを返す"""
        user_id = user["id"]
        cached = self._nobot_cache.get(user_id)
        if cached is not None:
            checked_at, is_nobot = cached
            if monotonic() - checked_at < NOBOT_CACHE_TTL:
                return is_nobot

        description = user.get("description")
        if description is None:
            try:
                profile = await asyncio.to_thread(self._msk.users_show, user_id=user_id)
            except Exception:
                # プロフィールを確認できない場合は、能動的な反応は控える。
                # 一時的な失敗をキャッシュせず、次回は再取得する。
                logger.warning(
                    "プロフィール取得に失敗したためタイムライン反応をスキップします: %s",
                    user.get("username"),
                    exc_info=True,
                )
                return True
            if isinstance(profile, dict):
                description = profile.get("description")

        is_nobot = NOBOT_HASHTAG_RE.search(description or "") is not None
        self._nobot_cache[user_id] = (monotonic(), is_nobot)
        return is_nobot

    async def handle(self, note: dict) -> None:
        """ホームタイムラインのノートに対する処理 (homeTimeline)"""
        if not note.get("text") or note.get("renoteId") or note["user"]["id"] == self._my_id:
            return

        text = note["text"]
        user = note["user"]
        user_id = user["id"]
        vis, forced_visible_ids = reply_audience(note)

        # メンション処理は MentionHandler が担当
        if self._my_id in note.get("mentions", []):
            return

        if "さんごちゃん" in text:
            if random.randint(1, 3) == 1:
                parts = text.split("さんごちゃん", 1)
                before = parts[0].strip()
                after = parts[1].strip()
                if before or after:
                    if await self._is_nobot(user):
                        logger.info(
                            "nobot指定のためタイムライン反応をスキップします: %s (%s)",
                            user.get("username"),
                            user_id,
                        )
                        return
                    name = self._store.get_display_name(user_id, user)
                    params = {
                        "text": f"呼んだ？ {name}さん",
                        "reply_id": note["id"],
                        "visibility": vis,
                    }
                    if forced_visible_ids is not None:
                        params["visible_user_ids"] = forced_visible_ids
                    await asyncio.to_thread(self._msk.notes_create, **params)
