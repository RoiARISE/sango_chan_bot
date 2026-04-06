import asyncio
import json

import websockets
from misskey import Misskey

from . import config
from .handlers import FollowHandler, MentionHandler, TimelineHandler
from .stores.nickname_store import NicknameStore


class MyBot:
    def __init__(self, msk: Misskey):
        self.msk = msk
        self.my_id = self.msk.i()["id"]

        self._store = NicknameStore(config.NICKNAME_FILE, msk, self.my_id)
        self._store.load()

        self._follow_handler = FollowHandler(msk, self._store)
        self._mention_handler = MentionHandler(msk, self._store, config.ADMIN_ID)
        self._timeline_handler = TimelineHandler(msk, self._store, self.my_id)

        print("botが起動しました")

    async def main_task(self):
        """ボットを起動し、WebSocketに接続する"""
        try:
            await asyncio.to_thread(
                self.msk.notes_create,
                text="うーん、うとうとしちゃってたみたい……？"
            )
        except Exception as e:
            print(f"起動ノートの投稿に失敗: {e}")

        await asyncio.to_thread(self._store.sync_followings)

        async with asyncio.TaskGroup() as tg:
            while True:
                try:
                    async with websockets.connect(config.WS_URL) as ws:
                        print("WebSocketに接続しました。イベントを待機します...")
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
                                    tg.create_task(self._follow_handler.handle(event_body))
                                elif event_type == "mention":
                                    tg.create_task(self._mention_handler.handle(event_body))
                            elif channel_id == "home" and event_type == "note":
                                tg.create_task(self._timeline_handler.handle(event_body))

                except websockets.exceptions.ConnectionClosed as e:
                    print(f"[main_task] ConnectionClosed: code={e.code}, reason={e.reason}")
                    await asyncio.sleep(5)
                except Exception as e:
                    print("[main_task] Error:", e)
                    await asyncio.sleep(5)
