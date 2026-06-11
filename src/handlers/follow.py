import asyncio
import logging

from misskey import Misskey

from ..stores.user_store import UserStore
from ..utils import create_mention_string

logger = logging.getLogger(__name__)


class FollowHandler:
    def __init__(self, msk: Misskey, store: UserStore):
        self._msk = msk
        self._store = store

    async def handle(self, user: dict) -> None:
        """フォローされたときの処理"""
        mention = create_mention_string(user)
        await asyncio.to_thread(
            self._msk.notes_create,
            text=f"フォローありがとうございます、{mention}さん\n「フォローして」とメンションしながら投稿すると、フォローバックするよ"
        )
        logger.info("フォローされました: %s", mention)
