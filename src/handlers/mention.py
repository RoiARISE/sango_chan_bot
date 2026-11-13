import asyncio
import logging
import random
import re
from typing import Awaitable, Callable, cast

from misskey import Misskey

from .. import config, intents, responses, utils
from ..services import image_utils, llm, speedtest
from ..stores.user_store import UserStore
from ..utils import create_mention_string

logger = logging.getLogger(__name__)


import misskey.exceptions

# MisskeyAPIException が詳細なエラー情報(info等)を出力できるように拡張
if not hasattr(misskey.exceptions.MisskeyAPIException, "_patched"):
    _orig_init = misskey.exceptions.MisskeyAPIException.__init__

    def _patched_init(self, response_dict: dict):
        _orig_init(self, response_dict)
        self.raw_error = response_dict.get("error", {})

    misskey.exceptions.MisskeyAPIException.__init__ = _patched_init
    misskey.exceptions.MisskeyAPIException.__str__ = lambda self: (
        f"{self.code}({self.id}): {self.message} "
        f"[詳細: {getattr(self, 'raw_error', {}).get('info', {})}]"
    )
    misskey.exceptions.MisskeyAPIException._patched = True


class MentionHandler:
    def __init__(
        self,
        msk: Misskey,
        store: UserStore,
        admin_id: str | None,
        cleanup_callback: Callable[[], Awaitable[tuple[int, int]]] | None = None
    ):
        self._msk = msk
        self._store = store
        self._admin_id = admin_id
        self._cleanup_callback = cleanup_callback
        self._todo_stop_events: dict[str, asyncio.Event] = {}
        # 同時実行数の確認と登録を競合させない
        self._todo_lock = asyncio.Lock()

    def _get_reply_kwargs(self, note: dict, text: str, **kwargs) -> dict:
        vis = note.get("visibility", "public")
        # 本文が空または空白のみの場合はフォールバック
        clean_text = text if (text and str(text).strip()) else "……？"

        # 文字数制限（Misskeyの上限は3000文字）
        max_chars = 3000
        trunc_notice = "\n\n（※文字数制限のため途中までを表示しています）"
        if len(clean_text) > max_chars:
            allowed_len = max_chars - len(trunc_notice)
            clean_text = clean_text[:allowed_len] + trunc_notice
            logger.warning("返信テキストが文字数上限(%d)を超えたため切り詰めました (元: %d文字)", max_chars, len(text))

        params: dict = {
            "text": clean_text,
            "reply_id": note["id"],
            "visibility": vis,
            **kwargs,
        }
        # CW は Misskey 側で返信に引き継がれないため、こちらで複製する
        cw = note.get("cw")
        if cw:
            params["cw"] = cw
        if vis == "specified":
            audience = utils.Audience.from_note(note, getattr(self._store, "_my_id", None))
            params["visible_user_ids"] = sorted(audience.recipients)
        return params

    async def _send_reply(self, note: dict, text: str, **kwargs) -> dict:
        params = self._get_reply_kwargs(note, text=text, **kwargs)
        logger.info(
            "返信ノート送信: text=%r (長さ: %d), reply_id=%s, visibility=%s, visible_user_ids=%s",
            params["text"][:30] + "..." if len(params["text"]) > 30 else params["text"],
            len(params["text"]),
            params.get("reply_id"),
            params.get("visibility"),
            params.get("visible_user_ids"),
        )
        try:
            return await asyncio.to_thread(self._msk.notes_create, **params)
        except Exception as e:
            logger.error("notes_create 失敗: params=%s, error=%s", params, e, exc_info=True)
            raise


    async def handle(self, note: dict) -> None:
        """メンションを受け取ったときの処理"""
        text = note.get("text") or ""

        if "フォローして" in text:
            await self._handle_follow_request(note)
            return
        elif "フォロー解除して" in text:
            await self._handle_unfollow_request(note)
            return
        elif "クリーンアップ" in text:
            await self._handle_cleanup_command(note)
            return

        user = note["user"]
        user_id = user["id"]

        # 管理者以外のユーザーに対してFF関係（相互フォロー）をチェック
        if user_id != self._admin_id:
            try:
                relation = await asyncio.to_thread(self._msk.users_show, user_id=user_id)
                relation = cast(dict, relation)
                is_mutual = relation.get("isFollowing") and relation.get("isFollowed")
                if not is_mutual:
                    logger.info("FF外からのメンションのため反応しません: %s (%s)", user.get("username"), user_id)
                    return
            except Exception:
                logger.error("ユーザー関係性の取得に失敗したため処理を中断します: %s", user_id, exc_info=True)
                return

        # Todoリマインダー完了チェック（「やった」返信で停止）
        reply_id = note.get("replyId")
        if "やった" in text and reply_id and reply_id in self._todo_stop_events:
            stop_event = self._todo_stop_events[reply_id]
            # リマインダーを止められるのは、Todoを作成した本人だけ
            if getattr(stop_event, "owner_id", None) == user_id:
                stop_event.set()
                await self._send_reply(note, text="終わらせたんだね、お疲れさま")
            return

        direct_images, direct_sensitive = self._extract_images_from_note(note)
        cleaned_text = re.sub(r'\+LLM|@\w+(?:@[\w.]+)?', '', text).strip()
        intent = intents.find_intent(text)

        if "って呼んで" in text or "と呼んで" in text:
            await self._handle_nickname_set(note)
        elif "呼び名を忘れて" in text or "あだ名を消して" in text:
            await self._handle_nickname_clear(note)
        elif "回線速度" in text and "計測" in text:
            await self._handle_speedtest(note)
        elif "todo" in text:
            await self._handle_todo(note)
        elif "何が好き？" in text and note.get("replyId") is not None:
            await asyncio.sleep(1)
            await self._send_reply(note, text="チョココーヒー よりもあ・な・た♪")
            await asyncio.sleep(10)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="さっきのなに……？"
            )
        elif re.search(r"(\d+)d(\d+)", text.lower()):
            await self._handle_dice(note)
        elif intent is not None:
            await self._handle_intent(note, intent, direct_images, direct_sensitive)
        elif cleaned_text or direct_images:
            await self._handle_llm(note, direct_images=direct_images, direct_sensitive=direct_sensitive)
        else:
            await self._handle_dice(note)

    async def _handle_follow_request(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        vis = note.get("visibility", "public")
        try:
            relation = await asyncio.to_thread(self._msk.users_show, user_id=user_id)
            relation = cast(dict, relation)
        except Exception:
            logger.error("Error fetching user relation", exc_info=True)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="ごめんね、今ちょっと調子が悪いみたい……",
                reply_id=note["id"],
                visibility=vis
            )
            return

        if not relation.get("isFollowed"):
            await asyncio.to_thread(
                self._msk.notes_create,
                text="……だれ？",
                reply_id=note["id"],
                visibility=vis
            )
            return

        if relation.get("isFollowing"):
            name = self._store.get_display_name(user_id, user)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{name}さん、もうフォローしてるよー",
                reply_id=note["id"],
                visibility=vis
            )
            return

        try:
            await asyncio.to_thread(self._msk.following_create, user_id=user_id)
            self._store.ensure_user(user_id, user.get("username", ""))
            logger.info("JSONに %s さんを登録しました", user.get("username"))

            name = self._store.get_display_name(user_id, user)
            mention = create_mention_string(user)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{mention} フォローバックしたよ、{name}さん。これからよろしくね",
                reply_id=note["id"],
                visibility=vis
            )
            logger.info("%s さんをフォローしました", name)
        except Exception:
            logger.error("フォロー作成エラー", exc_info=True)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="フォローしようとしたけど、うまくいかなかったみたい……",
                reply_id=note["id"],
                visibility=vis
            )

    async def _handle_unfollow_request(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        vis = note.get("visibility", "public")
        try:
            relation = await asyncio.to_thread(self._msk.users_show, user_id=user_id)
            relation = cast(dict, relation)
        except Exception:
            logger.error("Error fetching user relation", exc_info=True)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="ごめんね、今ちょっと調子が悪いみたい……",
                reply_id=note["id"],
                visibility=vis
            )
            return

        if relation.get("isFollowing"):
            mention = create_mention_string(user)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{mention} さよなら、になっちゃうのかな……",
                reply_id=note["id"],
                visibility=vis
            )
            await asyncio.sleep(10)
            try:
                await asyncio.to_thread(self._msk.following_delete, user_id=user_id)
                logger.info("%s さんのフォローを解除しました", user.get("username"))
                self._store.remove_user(user_id)
                logger.info("%s さんの情報をデータベースから削除しました", user.get("username"))
            except Exception:
                logger.error("フォロー解除またはデータ削除エラー", exc_info=True)
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text="フォロー解除しようとしたけど、うまくいかなかったみたい……",
                    reply_id=note["id"],
                    visibility=vis
                )
        else:
            mention = create_mention_string(user)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{mention} もともとフォローしてないよー",
                reply_id=note["id"],
                visibility=vis
            )

    async def _handle_cleanup_command(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        vis = note.get("visibility", "public")

        if user_id != self._admin_id:
            await asyncio.to_thread(
                self._msk.notes_create,
                text="この機能は使える人が限られてるんだ。ゴメンね",
                reply_id=note["id"],
                visibility=vis
            )
            return

        await asyncio.to_thread(
            self._msk.notes_create,
            text="関係性のクリーンアップを確認するから、少し待っててね……",
            reply_id=note["id"],
            visibility=vis
        )

        if self._cleanup_callback:
            try:
                checked_count, removed_count = await self._cleanup_callback()
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text=f"終わったよー\n検証対象: {checked_count}人\n削除/解除対象: {removed_count}人",
                    reply_id=note["id"],
                    visibility=vis
                )
            except Exception:
                logger.error("手動クリーンアップ実行エラー", exc_info=True)
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text="ごめん、クリーンアップ中にエラーが発生しちゃったみたい……",
                    reply_id=note["id"],
                    visibility=vis
                )
        else:
            await asyncio.to_thread(
                self._msk.notes_create,
                text="クリーンアップ機能が正しく設定されていないみたいだよ",
                reply_id=note["id"],
                visibility=vis
            )

    async def _handle_nickname_set(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        text = note.get("text", "")
        vis = note.get("visibility", "public")

        nickname = utils.extract_nickname(text)
        if not nickname:
            await asyncio.to_thread(
                self._msk.notes_create,
                text="えっと、名前がうまく聞き取れなかったかも……",
                reply_id=note["id"],
                visibility=vis
            )
            return
        if len(nickname) > config.MAX_NICKNAME_LENGTH:
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"えぇっと、その名前はちょっと長いかも……\n{config.MAX_NICKNAME_LENGTH}文字以内にしてほしいな",
                reply_id=note["id"],
                visibility=vis
            )
            return
        sanitized = utils.sanitize_nickname(nickname)
        if not utils.validate_nickname(sanitized):
            await asyncio.to_thread(
                self._msk.notes_create,
                text="えぇっと、その名前はちょっと……、だめかも……",
                reply_id=note["id"],
                visibility=vis
            )
            return
        self._store.set_nickname(user_id, sanitized, user.get("username", ""))
        await asyncio.to_thread(
            self._msk.notes_create,
            text=f"わかった。これからは{sanitized}さんって呼ぶね\nこれからもよろしくね、{sanitized}さん",
            reply_id=note["id"],
            visibility=vis
        )
        logger.info("あだ名を登録: %s -> %s", user_id, sanitized)

    async def _handle_nickname_clear(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        vis = note.get("visibility", "public")

        record = self._store.get(user_id)
        if record and record.get("nickname"):
            old_nickname = record["nickname"]
            self._store.clear_nickname(user_id)
            try:
                mentioner_data = await asyncio.to_thread(self._msk.users_show, user_id=user_id)
                new_name = self._store.get_display_name(user_id, mentioner_data)
            except Exception:
                new_name = user.get("username", user_id)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"うん、「{old_nickname}」さんって呼び方は忘れたよ。これからは{new_name}さんって呼ぶね",
                reply_id=note["id"],
                visibility=vis
            )
            logger.info("あだ名をリセット: %s", user_id)
        else:
            await asyncio.to_thread(
                self._msk.notes_create,
                text="もともと特別な呼び名は登録されていないみたいだよ",
                reply_id=note["id"],
                visibility=vis
            )

    async def _handle_speedtest(self, note: dict) -> None:
        user_id = note["user"]["id"]
        vis = note.get("visibility", "public")

        if user_id != self._admin_id:
            await asyncio.to_thread(
                self._msk.notes_create,
                text="この機能は使える人が限られてるんだ。ゴメンね",
                reply_id=note["id"],
                visibility=vis
            )
            return

        await asyncio.to_thread(
            self._msk.notes_create,
            text="了解。じゃあ計測してくるね",
            reply_id=note["id"],
            visibility=vis
        )
        try:
            speedtest_task = asyncio.create_task(
                asyncio.wait_for(speedtest.run_speedtest(), timeout=60)
            )
            await asyncio.sleep(10)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="計測中だよ、いまは話しかけないでね……",
                reply_id=note["id"],
                visibility=vis
            )
            speed_result = await speedtest_task

            if "ごめん、計測中にエラーが起きちゃったみたい" in speed_result:
                raise Exception(speed_result)

            if vis == "public":
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text=speed_result,
                    renote_id=note["id"],
                    visibility=vis
                )
            else:
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text=speed_result,
                    reply_id=note["id"],
                    visibility=vis
                )
        except asyncio.TimeoutError:
            logger.error("Speedtest エラー: タイムアウト")
            await asyncio.to_thread(
                self._msk.notes_create,
                text="ごめん、計測が1分経っても終わらないみたい……",
                reply_id=note["id"],
                visibility=vis
            )
        except Exception:
            logger.error("Speedtest エラー", exc_info=True)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="何かがおかしいかも……、もう一度やってみて？",
                reply_id=note["id"],
                visibility=vis
            )

    def _active_todo_count(self, user_id: str | None = None) -> int:
        """Count distinct Reminder events, optionally for one owner.

        The same event is registered under the original note id and each
        reminder note id, so count unique objects rather than dict entries.
        """
        events = {id(event): event for event in self._todo_stop_events.values()}
        if user_id is None:
            return len(events)
        return sum(
            1 for event in events.values()
            if getattr(event, "owner_id", None) == user_id
        )

    async def _handle_todo(self, note: dict) -> None:
        user_id = note["user"]["id"]
        vis = note.get("visibility", "public")
        note_id = note["id"]

        text_to_send = "これやった？"
        if user_id == self._admin_id:
            text_to_send = "ロイちゃん、これやった？"

        rejection = None
        stop_event: asyncio.Event | None = None
        async with self._todo_lock:
            if self._active_todo_count() >= config.MAX_ACTIVE_TODOS:
                rejection = "いまはリマインダーがいっぱいみたい……。少し時間をおいてね"
            elif self._active_todo_count(user_id) >= config.MAX_ACTIVE_TODOS_PER_USER:
                rejection = (
                    f"リマインダーは一度に{config.MAX_ACTIVE_TODOS_PER_USER}件までだよ。"
                    "終わったものから「やった」って教えてね"
                )
            else:
                stop_event = asyncio.Event()
                stop_event.owner_id = user_id  # type: ignore[attr-defined]
                # 反応を待つ前に登録し、同時に来た別のtodoが上限をすり抜けないようにする
                self._todo_stop_events[note_id] = stop_event

        if rejection is not None or stop_event is None:
            await self._send_reply(note, text=rejection or "いまはリマインダーを登録できないみたい……")
            return

        try:
            await asyncio.to_thread(self._msk.notes_reactions_create, note_id=note_id, reaction="👍")
        except Exception:
            self._todo_stop_events.pop(note_id, None)
            raise

        try:
            while not stop_event.is_set():
                delay = random.randint(600, 43200)
                logger.debug(
                    "Todoリマインダー 開始 (待機 %s秒 / 約%s分): %s",
                    delay, delay // 60, note_id
                )

                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                    break  # イベントが発火 → ループ終了
                except asyncio.TimeoutError:
                    pass  # 待機完了 → リマインダー送信へ

                if stop_event.is_set():
                    break

                logger.debug("Todoリマインダー実行 (vis: %s): %s", vis, note_id)
                try:
                    result = await asyncio.to_thread(
                        self._msk.notes_create,
                        text=text_to_send,
                        reply_id=note_id,
                        visibility=vis
                    )

                    # リマインダーのノートIDを追跡（「やった」返信の検知用）
                    if isinstance(result, dict):
                        created = result.get("createdNote", result)
                        reminder_id = created.get("id")
                        if reminder_id:
                            self._todo_stop_events[reminder_id] = stop_event
                except Exception:
                    logger.error("Todoリマインダー送信エラー: %s", note_id, exc_info=True)
                    break
        finally:
            # この stop_event に紐づく全エントリを削除
            to_remove = [k for k, v in self._todo_stop_events.items() if v is stop_event]
            for k in to_remove:
                self._todo_stop_events.pop(k, None)
            logger.debug("Todoリマインダー終了: %s", note_id)

    def _extract_images_from_note(self, note: dict) -> tuple[list[str], bool]:
        """ノートから画像URLのリストと、センシティブ画像が含まれているかのフラグを返す"""
        files = note.get("files", [])
        image_urls = []
        has_sensitive = False
        for f in files:
            file_type = f.get("type", "")
            if file_type.startswith("image/"):
                url = f.get("url")
                if url:
                    image_urls.append(url)
                    if f.get("isSensitive"):
                        has_sensitive = True
        return image_urls, has_sensitive

    async def _fetch_parent_images(
        self, reply_id: str, audience: utils.Audience | None = None
    ) -> tuple[list[str], bool]:
        """リプライ先の親ノートから画像URLとセンシティブフラグを取得する。

        親ノートの聴衆が今回の返信より狭い場合は、内容を広げないため取得しない。
        """
        try:
            parent_note = await asyncio.to_thread(self._msk.notes_show, note_id=reply_id)
            if isinstance(parent_note, dict):
                current = audience if audience is not None else utils.Audience("unknown")
                parent_audience = utils.Audience.from_note(
                    parent_note, getattr(self._store, "_my_id", None)
                )
                if not parent_audience.covers(current):
                    logger.info(
                        "親ノートの聴衆が返信より狭いため画像を取得しません: reply_id=%s, parent=%s, reply=%s",
                        reply_id,
                        parent_audience.visibility,
                        current.visibility,
                    )
                    return [], False
                return self._extract_images_from_note(parent_note)
        except Exception as e:
            logger.debug("親ノート画像取得スキップ/エラー (%s): %s", reply_id, e)
        return [], False

    async def _is_reply_to_me(self, note: dict) -> bool:
        """このノートが自分宛てのリプライ（会話スレッドの継続）かどうかを判定する"""
        reply_id = note.get("replyId")
        if not reply_id:
            return False

        my_id = getattr(self._store, "_my_id", None)
        if not my_id:
            return False

        # MisskeyのストリーミングAPIのnoteオブジェクトに reply が含まれている場合
        reply_note = note.get("reply")
        if isinstance(reply_note, dict):
            parent_uid = reply_note.get("userId") or reply_note.get("user", {}).get("id")
            return parent_uid == my_id

        # 含まれていない場合はAPIで親ノートを取得
        try:
            parent = await asyncio.to_thread(self._msk.notes_show, note_id=reply_id)
            if isinstance(parent, dict):
                parent_uid = parent.get("userId") or parent.get("user", {}).get("id")
                return parent_uid == my_id
        except Exception as e:
            logger.debug("親ノート取得エラー (%s): %s", reply_id, e)

        return False

    async def _handle_intent(
        self,
        note: dict,
        intent: intents.Intent,
        direct_images: list[str],
        direct_sensitive: bool,
    ) -> None:
        """意図つきのメンションを、定型文または LLM で処理する"""
        user = note["user"]
        display_name = self._store.get_display_name(user["id"], user)

        if intent.fixed:
            if intent.reply_only and note.get("replyId") is None:
                return
            await self._send_reply(note, text=intent.render_fallback(display_name))
            return

        if not config.LLM_ENABLE:
            await self._send_reply(note, text=intent.render_fallback(display_name))
            return

        await self._handle_llm(
            note,
            direct_images=direct_images,
            direct_sensitive=direct_sensitive,
            intent_hint=intent.build_hint(),
            fallback_text=intent.render_fallback(display_name),
        )

    async def _handle_llm(
        self,
        note: dict,
        direct_images: list[str] | None = None,
        direct_sensitive: bool = False,
        intent_hint: str | None = None,
        fallback_text: str | None = None,
    ) -> None:
        user = note["user"]
        user_id = user["id"]
        text = note.get("text") or ""
        is_reply = note.get("replyId") is not None
        audience = utils.Audience.from_note(note, getattr(self._store, "_my_id", None))

        async def process():
            try:
                await asyncio.to_thread(self._msk.notes_reactions_create, note_id=note["id"], reaction="💭")
            except Exception:
                pass

            cleaned_text = re.sub(r'\+LLM|@\w+(?:@[\w.]+)?', '', text).strip()
            user_name = self._store.get_display_name(user_id, user)

            # 画像URLの特定（直接添付画像、またはリプライ親ノートの画像）
            image_urls = list(direct_images) if direct_images else []
            has_sensitive = direct_sensitive
            if not image_urls and is_reply and note.get("replyId"):
                image_urls, has_sensitive = await self._fetch_parent_images(
                    note["replyId"], audience
                )

            # 画像URLはローカルで取得せず、検証したうえでAPIにそのまま渡す
            validated_image_urls = None
            if image_urls and config.LLM_ENABLE:
                validated_image_urls = await image_utils.validate_image_urls(image_urls)

            result = await llm.run_llm(
                user_id=user_id,
                user_name=user_name,
                text=cleaned_text,
                is_reply=is_reply,
                store=self._store,
                image_urls=validated_image_urls,
                has_sensitive_image=has_sensitive,
                intent_hint=intent_hint or "",
                audience=audience,
            )

            action = result.get("action", "reply")
            reaction = result.get("reaction") or "❤️"
            reply_text = result.get("reply", "")
            reason = result.get("reason", "")

            # 考え中リアクション 💭 を削除
            try:
                await asyncio.to_thread(self._msk.notes_reactions_delete, note_id=note["id"])
            except Exception:
                pass

            if fallback_text is not None and action != "reply":
                # 意図ヒント付きのメッセージには必ず返信させる
                logger.info(
                    "[%s] 意図ヒント付きのメッセージに LLM が返信しなかったため、定型文で返します: action=%s, reason=%s",
                    user_name, action, reason
                )
                await self._send_reply(note, text=fallback_text)
                return

            if action == "react":
                # リアクションのみ付与して会話終了（フェードアウト）
                logger.info(
                    "[%s] 会話をリアクションでフェードアウト終了します: reaction=%s, reason=%s",
                    user_name, reaction, reason
                )
                try:
                    await asyncio.to_thread(self._msk.notes_reactions_create, note_id=note["id"], reaction=reaction)
                except Exception as e:
                    logger.warning("終了リアクション付与に失敗: %s", e)

            elif action == "none":
                # 既読スルー（何もしない）
                logger.info("[%s] 会話を沈黙で終了します: reason=%s", user_name, reason)

            else:
                # 通常返信 (action == "reply")
                if reaction:
                    try:
                        await asyncio.to_thread(self._msk.notes_reactions_create, note_id=note["id"], reaction=reaction)
                    except Exception:
                        pass
                await self._send_reply(note, text=reply_text)

        task = asyncio.create_task(process())
        task.add_done_callback(
            lambda t: logger.error("LLMプロセスエラー: %s", t.exception()) if t.exception() else None
        )

    async def _handle_dice(self, note: dict) -> None:
        text = note.get("text", "")
        match = re.search(r"(\d+)d(\d+)", text.lower())
        if not match:
            return
        count_str, sides_str = match.groups()
        rolls = responses.roll_dice(count_str, sides_str)
        if not rolls:
            await self._send_reply(note, text="……うーん？")
        else:
            reply = f"{rolls[0]} だよ" if len(rolls) == 1 else f"{', '.join(map(str, rolls))} だよ"
            user_mention = create_mention_string(note["user"])
            await self._send_reply(note, text=f"{user_mention} {reply}")
