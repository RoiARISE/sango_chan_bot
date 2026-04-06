import asyncio
import logging
import re
from typing import Callable, cast

from misskey import Misskey

from .. import config, responses, utils
from ..services import llm, speedtest
from ..stores.nickname_store import NicknameStore
from ..utils import create_mention_string

logger = logging.getLogger(__name__)


class MentionHandler:
    def __init__(self, msk: Misskey, store: NicknameStore, admin_id: str | None):
        self._msk = msk
        self._store = store
        self._admin_id = admin_id

    async def handle(self, note: dict) -> None:
        """メンションを受け取ったときの処理"""
        text = note.get("text", "")

        if "フォローして" in text:
            await self._handle_follow_request(note)
        elif "フォロー解除して" in text:
            await self._handle_unfollow_request(note)
        elif "って呼んで" in text or "と呼んで" in text:
            await self._handle_nickname_set(note)
        elif "呼び名を忘れて" in text or "あだ名を消して" in text:
            await self._handle_nickname_clear(note)
        elif "回線速度" in text and "計測" in text:
            await self._handle_speedtest(note)
        elif "todo" in text:
            await self._handle_todo(note)
        elif "+LLM" in text or "さんご" in text:
            await self._handle_llm(note)
        elif "さんごちゃーん" in text or "さんごちゃ〜ん" in text:
            vis = note.get("visibility", "public")
            await asyncio.sleep(1)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="は〜い",
                reply_id=note["id"],
                visibility=vis
            )
        elif "何が好き？" in text and note.get("replyId") is not None:
            vis = note.get("visibility", "public")
            await asyncio.sleep(1)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="チョココーヒー よりもあ・な・た♪",
                reply_id=note["id"],
                visibility=vis
            )
            await asyncio.sleep(10)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="さっきのなに……？"
            )
        else:
            handled = await self._dispatch_command_list(note)
            if not handled:
                await self._handle_dice(note)

    async def _handle_follow_request(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        try:
            relation = await asyncio.to_thread(self._msk.users_show, user_id=user_id)
            relation = cast(dict, relation)
        except Exception:
            logger.error("Error fetching user relation", exc_info=True)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="ごめんね、今ちょっと調子が悪いみたい……",
                reply_id=note["id"]
            )
            return

        if not relation.get("isFollowed"):
            await asyncio.to_thread(
                self._msk.notes_create,
                text="……だれ？",
                reply_id=note["id"]
            )
            return

        if relation.get("isFollowing"):
            name = self._store.get_display_name(user_id, user)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{name}さん、もうフォローしてるよー",
                reply_id=note["id"]
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
                reply_id=note["id"]
            )
            logger.info("%s さんをフォローしました", name)
        except Exception:
            logger.error("フォロー作成エラー", exc_info=True)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="フォローしようとしたけど、うまくいかなかったみたい……",
                reply_id=note["id"]
            )

    async def _handle_unfollow_request(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        try:
            relation = await asyncio.to_thread(self._msk.users_show, user_id=user_id)
            relation = cast(dict, relation)
        except Exception:
            logger.error("Error fetching user relation", exc_info=True)
            await asyncio.to_thread(
                self._msk.notes_create,
                text="ごめんね、今ちょっと調子が悪いみたい……",
                reply_id=note["id"]
            )
            return

        if relation.get("isFollowing"):
            mention = create_mention_string(user)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{mention} さよなら、になっちゃうのかな……",
                reply_id=note["id"]
            )
            await asyncio.sleep(10)
            try:
                await asyncio.to_thread(self._msk.following_delete, user_id=user_id)
                logger.info("%s さんのフォローを解除しました", user.get("username"))
                self._store.remove_user(user_id)
                logger.info("%s さんの情報をnickname.jsonから削除しました", user.get("username"))
            except Exception:
                logger.error("フォロー解除またはJSON削除エラー", exc_info=True)
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text="フォロー解除しようとしたけど、うまくいかなかったみたい……",
                    reply_id=note["id"]
                )
        else:
            mention = create_mention_string(user)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{mention} もともとフォローしてないよー",
                reply_id=note["id"]
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
                visibility=vis
            )
            speed_result = await speedtest_task

            if "ごめん、計測中にエラーが起きちゃったみたい" in speed_result:
                raise Exception(speed_result)

            if vis == "followers":
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text=speed_result,
                    reply_id=note["id"],
                    visibility=vis
                )
            else:
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text=speed_result,
                    renote_id=note["id"],
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
                text="速度測定中にエラーが発生しました。後でもう一度お試しください。",
                reply_id=note["id"],
                visibility=vis
            )

    async def _handle_todo(self, note: dict) -> None:
        user_id = note["user"]["id"]
        vis = note.get("visibility", "public")
        note_id = note["id"]

        text_to_send = "これやった？"
        if user_id == self._admin_id:
            text_to_send = "管理者ちゃん、これやった？"

        delay = 60
        logger.debug("Todoリマインダー 開始 (待機 %s秒): %s", delay, note_id)
        await asyncio.sleep(delay)

        logger.debug("Todoリマインダー実行 (vis: %s): %s", vis, note_id)
        if vis == "followers":
            await asyncio.to_thread(self._msk.notes_create, text=text_to_send, reply_id=note_id, visibility=vis)
        else:
            await asyncio.to_thread(self._msk.notes_create, text=text_to_send, renote_id=note_id, visibility=vis)

    async def _handle_llm(self, note: dict) -> None:
        user = note["user"]
        user_id = user["id"]
        text = note.get("text", "")
        vis = note.get("visibility", "public")
        is_reply = note.get("replyId") is not None

        async def process():
            await asyncio.to_thread(self._msk.notes_reactions_create, note_id=note["id"], reaction="💭")
            cleaned_text = (
                text
                .replace("+LLM", "")
                .replace("@sango", "")
                .replace("@sango@3.5mbps.net", "")
                .replace("@miiko", "")
                .replace("@miiko@3.5mbps.net", "")
                .replace("@ten", "")
                .replace("@ten@3.5mbps.net", "")
                .strip()
            )
            user_name = self._store.get_display_name(user_id, user)
            reply = await llm.run_llm(user_id, user_name, cleaned_text, is_reply)
            await asyncio.to_thread(
                self._msk.notes_create,
                text=reply,
                reply_id=note["id"],
                visibility=vis
            )

        task = asyncio.create_task(process())
        task.add_done_callback(
            lambda t: logger.error("LLMプロセスエラー: %s", t.exception()) if t.exception() else None
        )

    def _build_command_list(
        self, user_id: str, user: dict, vis: str
    ) -> list[tuple[tuple[str, ...], str | Callable[[], str], bool | None]]:
        return [
            (("はじめまして",), "はじめまして、わたしを見つけてくれてありがとう。これからよろしくね", None),
            (("こんにちは",), "こんにちは、どうしたの？", None),
            (("自己紹介", "あなたは？"), "わたしはここ「3.SMbps.net」の看板娘、さんごです。……看板娘は自称だけどね\nあなたのことも、さんごに教えて欲しいな", None),
            (("よしよし", "なでなで"), "わたしの頭なんか撫でて、楽しい？ えっと、あなたが喜んでくれるなら、いいんだけど……", None),
            (("にゃーん",), "にゃ〜ん", None),
            (("罵って",), responses.get_random_response("to_you_abuse"), None),
            (("ping",), "pong？", None),
            (("さんごちゃん？",), f"どうしたの？ {self._store.get_display_name(user_id, user)}さん", None),
            (("今何時", "いまなんじ"), responses.get_current_time_response, None),
            (("ちくわ大明神",), "…なに？", True),
        ]

    async def _dispatch_command_list(self, note: dict) -> bool:
        user = note["user"]
        user_id = user["id"]
        text = note.get("text", "")
        vis = note.get("visibility", "public")
        is_reply = note.get("replyId") is not None

        for keywords, response, reply_rule in self._build_command_list(user_id, user, vis):
            if reply_rule is not None:
                if reply_rule is True and not is_reply:
                    continue
                if reply_rule is False and is_reply:
                    continue
            if any(kw in text for kw in keywords):
                if callable(response):
                    response = response()
                await asyncio.to_thread(
                    self._msk.notes_create,
                    text=response,
                    reply_id=note["id"],
                    visibility=vis
                )
                return True
        return False

    async def _handle_dice(self, note: dict) -> None:
        text = note.get("text", "")
        vis = note.get("visibility", "public")
        match = re.search(r"(\d+)d(\d+)", text.lower())
        if not match:
            return
        count_str, sides_str = match.groups()
        rolls = responses.roll_dice(count_str, sides_str)
        if not rolls:
            await asyncio.to_thread(
                self._msk.notes_create,
                text="……うーん？",
                reply_id=note["id"],
                visibility=vis
            )
        else:
            reply = f"{rolls[0]} だよ" if len(rolls) == 1 else f"{', '.join(map(str, rolls))} だよ"
            user_mention = create_mention_string(note["user"])
            await asyncio.to_thread(
                self._msk.notes_create,
                text=f"{user_mention} {reply}",
                reply_id=note["id"],
                visibility=vis
            )
