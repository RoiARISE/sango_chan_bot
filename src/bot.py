import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import websockets
from misskey import Misskey

from . import config, responses
from .handlers import FollowHandler, MentionHandler, TimelineHandler
from .stores.user_store import UserStore

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

        self._store = UserStore(config.USER_DATA_FILE, msk, self.my_id)
        self._store.load()

        self._follow_handler = FollowHandler(msk, self._store)
        self._mention_handler = MentionHandler(
            msk, self._store, config.ADMIN_ID, cleanup_callback=self.run_manual_cleanup
        )
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

    async def timesignal_task(self):
        """時報タスク: 毎時0分に定期投稿 (JST)"""
        JST = timezone(timedelta(hours=9))
        while True:
            now = datetime.now(JST)
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            await asyncio.sleep((next_hour - now).total_seconds())

            hour = next_hour.hour
            if hour in responses.SIGNALS:
                try:
                    await asyncio.to_thread(self.msk.notes_create, text=responses.SIGNALS[hour])
                    logger.info("時報投稿: %d時", hour)
                except Exception:
                    logger.error("時報投稿に失敗", exc_info=True)

    async def relationship_cleanup_task(self):
        """定期的にユーザーとのFF関係をチェックし、崩れていたら解除・削除する (毎日 00:00 と 12:00 JST に実行)"""
        logger.info("FF関係クリーンアップタスクを起動しました")
        JST = timezone(timedelta(hours=9))
        while True:
            now = datetime.now(JST)
            today_00 = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_12 = now.replace(hour=12, minute=0, second=0, microsecond=0)
            tomorrow_00 = today_00 + timedelta(days=1)

            if now < today_00:
                next_run = today_00
            elif now < today_12:
                next_run = today_12
            else:
                next_run = tomorrow_00

            sleep_seconds = (next_run - now).total_seconds()
            logger.info(
                "次回の定期クリーンアップ実行予定時刻 (JST): %s (待機時間: %.1f秒)",
                next_run.strftime("%Y-%m-%d %H:%M:%S"),
                sleep_seconds
            )
            await asyncio.sleep(sleep_seconds)

            logger.info("FF関係の定期クリーンアップを開始します...")
            try:
                # 定期チェック前にフォロー中ユーザーのリストを同期して最新化
                await asyncio.to_thread(self._store.sync_followings)
                await self.cleanup_inactive_relations()
            except Exception:
                logger.error("FF関係のクリーンアップ実行中にエラーが発生しました", exc_info=True)

    async def run_manual_cleanup(self) -> tuple[int, int]:
        """手動クリーンアップ実行用ラッパー: 同期を行ってからクリーンアップを実行する"""
        await asyncio.to_thread(self._store.sync_followings)
        return await self.cleanup_inactive_relations()

    async def cleanup_inactive_relations(self) -> tuple[int, int]:
        """相互フォロー（FF関係）が絶たれているユーザーを自動解除＆JSONから削除する"""
        user_ids = list(self._store._data.keys())
        if not user_ids:
            return 0, 0

        # 管理者は除外
        user_ids = [uid for uid in user_ids if uid != config.ADMIN_ID]
        if not user_ids:
            return 0, 0

        logger.info("検証対象ユーザー数: %d人", len(user_ids))
        checked_count = len(user_ids)
        removed_count = 0

        # 50人ずつ一括チェック
        chunk_size = 50
        for i in range(0, len(user_ids), chunk_size):
            chunk = user_ids[i : i + chunk_size]
            try:
                relations = await asyncio.to_thread(self.msk.users_relation, user_id=chunk)
                if isinstance(relations, dict):
                    relations = [relations]

                for rel in relations:
                    uid = rel.get("id")
                    if not uid:
                        continue

                    is_following = rel.get("isFollowing", False)
                    is_followed = rel.get("isFollowed", False)

                    # 相互フォローでない場合
                    if not (is_following and is_followed):
                        user_record = self._store.get(uid)
                        username = user_record.get("username", "unknown") if user_record else "unknown"

                        logger.info(
                            "FF外ユーザーを検出しました: %s (%s) [Following:%s, Followed:%s]",
                            username, uid, is_following, is_followed
                        )

                        # フォロー中なら解除
                        if is_following:
                            try:
                                await asyncio.to_thread(self.msk.following_delete, user_id=uid)
                                logger.info("%s さんのフォローを自動解除しました", username)
                            except Exception:
                                logger.error("%s さんのフォロー自動解除に失敗しました", username, exc_info=True)

                        # JSONストアから削除
                        self._store.remove_user(uid)
                        logger.info("%s さんのデータをJSONから削除しました", username)
                        removed_count += 1
            except Exception:
                logger.error("関係性チェックのバッチ実行中にエラーが発生しました", exc_info=True)

            await asyncio.sleep(2)
        return checked_count, removed_count
