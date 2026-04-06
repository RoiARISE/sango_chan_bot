import asyncio
import json
import logging

import websockets
from misskey import Misskey

from . import config
from .handlers import FollowHandler, MentionHandler, TimelineHandler
from .stores.nickname_store import NicknameStore

logger = logging.getLogger(__name__)


async def _safe_run(coro, name: str):
    """ハンドラーコルーチンを実行し、例外をログに記録する"""
    try:
        await coro
    except Exception:
        logger.error("[%s] ハンドラーエラー", name, exc_info=True)


class MyBot:
    def __init__(self, msk: Misskey):
        self.msk = msk
        self.my_id = self.msk.i()["id"]

        self._store = NicknameStore(config.NICKNAME_FILE, msk, self.my_id)
        self._store.load()

        self._follow_handler = FollowHandler(msk, self._store)
        self._mention_handler = MentionHandler(msk, self._store, config.ADMIN_ID)
        self._timeline_handler = TimelineHandler(msk, self._store, self.my_id)

        logger.info("botが起動しました")

    async def main_task(self):
        """ボットを起動し、WebSocketに接続する"""
        try:
            await asyncio.to_thread(
                self.msk.notes_create,
                text="うーん、うとうとしちゃってたみたい……？"
            )
        except Exception:
            logger.error("起動ノートの投稿に失敗", exc_info=True)

        await asyncio.to_thread(self._store.sync_followings)

        while True:
            try:
                async with websockets.connect(config.WS_URL) as ws:
                    logger.info("WebSocketに接続しました。イベントを待機します...")
                    await ws.send(json.dumps({
                        "type": "connect", "body": {"channel": "main", "id": "main"}
                    }))
                    await ws.send(json.dumps({
                        "type": "connect", "body": {"channel": "homeTimeline", "id": "home"}
                    }))

                    while True:
                        data = json.loads(await ws.recv())
                        if data.get("type") != "channel":
                            continue

                        body = data["body"]
                        event_type = body.get("type")
                        event_body = body.get("body")
                        channel_id = body.get("id")

                        if channel_id == "main":
                            if event_type == "followed":
                                asyncio.create_task(
                                    _safe_run(self._follow_handler.handle(event_body), "follow")
                                )
                            elif event_type == "mention":
                                asyncio.create_task(
                                    _safe_run(self._mention_handler.handle(event_body), "mention")
                                )
                        elif channel_id == "home" and event_type == "note":
                            asyncio.create_task(
                                _safe_run(self._timeline_handler.handle(event_body), "timeline")
                            )

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("[main_task] ConnectionClosed: code=%s, reason=%s", e.code, e.reason)
                await asyncio.sleep(5)
            except Exception:
                logger.error("[main_task] Error", exc_info=True)
                await asyncio.sleep(5)
