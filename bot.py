import asyncio
import json
import re
import random
import threading
import time
import queue
from typing import cast, Callable

import websockets
from misskey import Misskey

from sango_chan_bot import config, responses, utils


class MyBot:
    def __init__(self):
        self.msk = Misskey(config.INSTANCE_URL, i=config.TOKEN)
        self.my_id = self.msk.i()['id']
        self.admin_id = config.ADMIN_ID
        self.nicknames = self._load_nicknames()
        print("botが起動しました")

    # --- データ管理メソッド ---
    def _load_nicknames(self):
        try:
            with open(config.NICKNAME_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save_nicknames(self):
        with open(config.NICKNAME_FILE, "w", encoding="utf-8") as f:
            json.dump(self.nicknames, f, ensure_ascii=False, indent=2)

    def _sync_followings(self):
        """起動時にフォロー中のユーザー情報を同期する"""
        try:
            followings = self.msk.users_following(user_id=self.my_id, limit=100)
            added_count = 0
            for item in followings:
                user = item["followee"]
                if user["id"] not in self.nicknames:
                    self.nicknames[user["id"]] = {"nickname": "", "username": user["username"]}
                    added_count += 1

            if added_count > 0:
                self._save_nicknames()
            print(f"✅フォロー同期完了: {added_count}件のユーザーを追加しました。")
        except Exception as e:
            print(f"フォロー同期エラー: {e}")

    # --- ヘルパーメソッド (共通処理) ---
    def _create_mention_string(self, user):
        """ユーザー情報からメンション文字列を生成する (コードの重複を解消)"""
        username = user.get('username')
        host = user.get('host')
        return f"@{username}@{host}" if host else f"@{username}"

    def _get_user_display_name(self, user_id, user_data=None):
        """あだ名、表示名、ユーザー名の順で名前を取得する"""
        if user_id in self.nicknames and self.nicknames[user_id].get("nickname"):  # あだ名を優先
            return self.nicknames[user_id]["nickname"]
        if user_data and user_data.get("name"):  # APIから取得した表示名を次に
            return user_data["name"]
        if user_data and user_data.get("username"):  # 最後にユーザー名
            return user_data["username"]
        return user_id  # それでもなければIDを返す

    def _delayed_reply(self, note_id, user_id, vis, delay):
        """
        指定時間後にリマインド投稿を行う（別スレッドで実行される）。
        """
        try:
            # 1. 待機 (これは別スレッドなので time.sleep でOKらしい)
            print(f"Todoリマインダー スレッド開始 (待機 {delay}秒): {note_id}")
            time.sleep(delay)

            # 2. テキスト準備
            text_to_send = 'これやった？'
            if user_id == self.admin_id:
                text_to_send = '管理者ちゃん、これやった？'

            # 3. visibility に応じて引用/リプライを切り替え
            print(f"Todoリマインダー実行 (vis: {vis}): {note_id}")
            if vis == "followers":
                # フォロワー限定投稿だった場合は「リプライ」
                self.msk.notes_create(text=text_to_send, reply_id=note_id, visibility=vis)
            else:
                # それ以外は「引用」
                self.msk.notes_create(text=text_to_send, renote_id=note_id, visibility=vis)
        except Exception as e:
            # APIエラー（ノートが削除されたなど）が起きても落とさない
            print(f"delayed_reply スレッド エラー: {e}")

    # --- イベントハンドラ ---
    def _on_followed(self, user):
        """フォローされたときの処理"""
        mention = self._create_mention_string(user)
        self.msk.notes_create(
            text=f"フォローありがとうございます、{mention}さん\n「フォローして」とメンションしながら投稿すると、フォローバックするよ"
        )
        print(f"フォローされました: {mention}")

    def _on_mention(self, note):
        """メンションを受け取ったときの処理"""
        user = note['user']
        text = note.get('text', '')
        # --- フォロー/フォロー解除処理 ---
        if "フォローして" in text:
            user_id = user['id']

            try:
                # ユーザーとの関係性を取得
                relation = self.msk.users_show(user_id=user_id)
                relation = cast(dict, relation)
            except Exception as e:
                print(f"Error fetching user relation: {e}")
                self.msk.notes_create(text="ごめんね、今ちょっと調子が悪いみたい……", reply_id=note['id'])
                return  # エラー時はここで処理終了
            # 1. 相手が自分をフォローしているか確認 (isFollowed)
            # (元のコードのロジックを再現)
            if not relation.get('isFollowed'):
                self.msk.notes_create(text="……だれ？", reply_id=note['id'])
                return
            # 2. 自分が相手をフォローしているか確認 (isFollowing)
            if relation.get('isFollowing'):
                # ヘルパーメソッドで名前を取得
                name = self._get_user_display_name(user_id, user)
                self.msk.notes_create(text=f"{name}さん、もうフォローしてるよー", reply_id=note['id'])
                return

            # 3. (フォローされていて、フォローしていない場合) フォローバック実行
            try:
                self.msk.following_create(user_id=user_id)

                # nicknamesに登録
                if user_id not in self.nicknames:
                    self.nicknames[user_id] = {"nickname": "", "username": user.get("username", "")}
                    self._save_nicknames()  # クラスのメソッドで保存
                    print(f"JSONに {user.get('username')} さんを登録しました")

                # ヘルパーメソッドで名前とメンション文字列を取得
                name = self._get_user_display_name(user_id, user)
                mention = self._create_mention_string(user)
                self.msk.notes_create(text=f'{mention} フォローバックしたよ、{name}さん。これからよろしくね', reply_id=note['id'])
                print(f"{name} さんをフォローしました。")

            except Exception as e:
                print(f"フォロー作成エラー: {e}")
                self.msk.notes_create(text="フォローしようとしたけど、うまくいかなかったみたい……", reply_id=note['id'])
            return

        # --- フォロー解除処理 ---
        elif "フォロー解除して" in text:
            user_id = user['id']

            try:
                relation = self.msk.users_show(user_id=user_id)
                relation = cast(dict, relation)
            except Exception as e:
                print(f"Error fetching user relation: {e}")
                return  # エラー時は処理終了

            if relation.get('isFollowing'):   # フォローしてる場合
                mention = self._create_mention_string(user)
                self.msk.notes_create(text=f'{mention} さよなら、になっちゃうのかな……', reply_id=note['id'])

                try:
                    self.msk.following_delete(user_id=user_id)
                    print(f"{user.get('username')} さんのフォローを解除しました")

                    if user_id in self.nicknames:
                        del self.nicknames[user_id]
                        self._save_nicknames()  # 変更をJSONファイルに保存
                        print(f"{user.get('username')} さんの情報をnickname.jsonから削除しました。")  # JSONからユーザー情報を削除

                except Exception as e:
                    print(f"フォロー解除またはJSON削除エラー: {e}")
                    self.msk.notes_create(text="フォロー解除しようとしたけど、うまくいかなかったみたい……", reply_id=note['id'])
            else:  # 未フォローの場合
                mention = self._create_mention_string(user)
                self.msk.notes_create(text=f"{mention} もともとフォローしてないよー", reply_id=note['id'])
            return

    def _on_timeline_note(self, note):
        """ホームタイムラインのノートに対する処理 (homeTimeline)"""
        if not note.get("text") or note.get('renoteId') or note["user"]["id"] == self.my_id:
            return

        text = note["text"]
        user = note['user']
        user_id = user['id']
        vis = note.get("visibility", "public")  # 投稿範囲の設定
        is_reply = note.get('replyId') is not None  # リプを含めるか否か
        match = re.search(r"(\d+)d(\d+)", text.lower())
        CHARS_TO_STRIP = " 　\n\t。、？！?!"

        if self.my_id in note.get('mentions', []):  # メンション処理

            # --- あだ名設定処理 ---
            if "って呼んで" in text or "と呼んで" in text:
                nickname = utils.extract_nickname(text)
                if not nickname:
                    self.msk.notes_create(text="えっと、名前がうまく聞き取れなかったかも……", reply_id=note["id"], visibility=vis)
                    return
                if len(nickname) > config.MAX_NICKNAME_LENGTH:
                    self.msk.notes_create(
                        text=f"えぇっと、その名前はちょっと長いかも……\n{config.MAX_NICKNAME_LENGTH}文字以内にしてほしいな",
                        reply_id=note["id"],
                        visibility=vis
                    )
                    return
                sanitized = utils.sanitize_nickname(nickname)
                if not utils.validate_nickname(sanitized):
                    self.msk.notes_create(text="えぇっと、その名前はちょっと……、だめかも……", reply_id=note["id"], visibility=vis)
                    return
                if user_id not in self.nicknames:
                    self.nicknames[user_id] = {"username": user.get("username", "")}
                self.nicknames[user_id]["nickname"] = sanitized
                self._save_nicknames()
                self.msk.notes_create(
                    text=f"わかった。これからは{sanitized}さんって呼ぶね\nこれからもよろしくね、{sanitized}さん",
                    reply_id=note["id"],
                    visibility=vis
                )
                print(f"あだ名を登録: {user_id} -> {sanitized}")
                return

            elif "呼び名を忘れて" in text or "あだ名を消して" in text:
                if user_id in self.nicknames and self.nicknames[user_id].get("nickname"):
                    old_nickname = self.nicknames[user_id]["nickname"]
                    self.nicknames[user_id]["nickname"] = ""
                    self._save_nicknames()

                    try:
                        mentioner_data = self.msk.users_show(user_id=user_id)
                        new_name = self._get_user_display_name(user_id, mentioner_data)
                    except Exception:
                        new_name = user.get("username", "user_id")

                    self.msk.notes_create(
                        text=f"うん、「{old_nickname}」さんって呼び方は忘れたよ。これからは{new_name}さんって呼ぶね",
                        reply_id=note["id"],
                        visibility=vis
                    )
                    print(f"あだ名をリセット: {user_id}")
                else:
                    self.msk.notes_create(text="もともと特別な呼び名は登録されていないみたいだよ", reply_id=note["id"], visibility=vis)
                return

            if "回線速度" in text and "計測" in text:
                if user_id == self.admin_id:  # 管理者かどうかをチェック
                    self.msk.notes_create(text="了解。じゃあ計測してくるね", reply_id=note['id'], visibility=vis)
                    result_queue = queue.Queue()
                    threading.Thread(target=responses.run_speedtest, args=(result_queue,), daemon=True).start()
                    time.sleep(10)
                    self.msk.notes_create(text="計測中だよ、いまは話しかけないでね……")

                    try:
                        speed_result = result_queue.get(timeout=60)  # (タイムアウトを60秒=1分に設定)
                        if "ごめん、計測中にエラー" in speed_result:
                            raise Exception(speed_result)

                        if vis == "followers":
                            self.msk.notes_create(text=speed_result, reply_id=note['id'], visibility=vis)
                        else:
                            self.msk.notes_create(text=speed_result, renote_id=note['id'], visibility=vis)

                    except queue.Empty:
                        print("Speedtest エラー: タイムアウト")
                        self.msk.notes_create(text="ごめん、計測が1分経っても終わらないみたい……", reply_id=note['id'], visibility=vis)
                    except Exception as e:
                        print(f"Speedtest エラー: {e}")
                        self.msk.notes_create(text=str(e), reply_id=note['id'], visibility=vis)  # e (エラーメッセージ) を投稿
                else:
                    self.msk.notes_create(text="この機能は使える人が限られてるんだ。ゴメンね", reply_id=note['id'], visibility=vis)
                return

            if "todo" in text:
                print("todoを検知")
                note_id = note["id"]
                delay = 60  # 待機時間

                threading.Thread(target=self._delayed_reply, args=(note_id, user_id, vis, delay), daemon=True).start()

            if ("さんごちゃーん" in text or "さんごちゃ〜ん" in text):
                time.sleep(1)
                self.msk.notes_create(text="は〜い", reply_id=note['id'], visibility=vis)
                return  # 処理完了

            if "何が好き？" in text and is_reply:
                time.sleep(1)  # 👈 1秒待機
                self.msk.notes_create(text="チョココーヒー よりもあ・な・た♪", reply_id=note['id'], visibility=vis)
                time.sleep(10)  # 👈 10秒待機
                self.msk.notes_create(text="さっきのなに……？")
                return

            # リストの全項目を3個のタプルに統一 ▼▼▼
            mention_command_list: list[tuple[tuple[str, ...], str | Callable[[], str], bool | None]] = [
                # ( (キーワード,), "応答", リプライ制限 )
                (("はじめまして",), "はじめまして、わたしを見つけてくれてありがとう。これからよろしくね", None),
                (("こんにちは",), "こんにちは、どうしたの？", None),
                (("自己紹介", "あなたは？"), "わたしはここ「3.SMbps.net」の看板娘、さんごです。……看板娘は自称だけどね\nあなたのことも、さんごに教えて欲しいな", None),  # ← None を追加
                (("よしよし", "なでなで"), "わたしの頭なんか撫でて、楽しい？ えっと、あなたが喜んでくれるなら、いいんだけど……", None),
                (("にゃーん",), "にゃ〜ん", None),
                (("罵って",), responses.get_random_response('to_you_abuse'), None),
                (("ping",), "pong？", None),
                (("さんごちゃん？",), f"どうしたの？ {self._get_user_display_name(user_id, user)}さん", None),
                (("今何時", "いまなんじ"), responses.get_current_time_response, None),
                (("ちくわ大明神",), "…なに？", True),
            ]

            for keywords, response, reply_rule in mention_command_list:
                if reply_rule is not None:
                    if reply_rule is True and not is_reply:
                        continue
                    if reply_rule is False and is_reply:
                        continue
                if any(kw in text for kw in keywords):
                    if callable(response):
                        response = response()
                    self.msk.notes_create(text=response, reply_id=note['id'], visibility=vis)
                    return

            if match:
                count_str, sides_str = match.groups()
                rolls = responses.roll_dice(count_str, sides_str)
                if not rolls:
                    # (上限を超えたか、0d0 だった場合)
                    self.msk.notes_create(text="……うーん？", reply_id=note["id"], visibility=vis)
                else:
                    if len(rolls) == 1:
                        reply = f"{rolls[0]} だよ"
                    else:
                        reply = f"{', '.join(map(str, rolls))} だよ"

                    user_mention = self._create_mention_string(user)
                    self.msk.notes_create(text=f"{user_mention} {reply}", reply_id=note["id"], visibility=vis)
            return

        # 2. "exact" モード用に、投稿の前後を掃除
        cleaned_text = text.strip(CHARS_TO_STRIP)
        # 3. "context" モード用の文字数上限
        CONTEXT_LIMIT = 10  # 👈 前後に5文字まで許容 (この数字は自由に変更してください)
        # 4. タイムラインキーワードの定義 (一致モードで分ける)
        timeline_keywords: list[tuple[tuple[str, ...], str | Callable[[], str], bool | None, str]] = [
            # ( (キーワード,), "応答", リプライ制限, 一致モード )

            # --- "exact" (完全一致) ---
            (("おはよ",), f"おはよ、よく眠れた？ わたしは{responses.get_random_response('morning')}", False, "exact"),
            (("おそよ",), "遅いよ、ねぼすけさん。なんで寝坊したのか、ちゃんと説明して？", False, "exact"),
            (("二度寝",), responses.get_random_response('two_time_sleep'), False, "exact"),
            (("にゃーん",), "にゃーん。……えへへ、わたしも混ぜて？", False, "exact"),
            (("ぬるぽ",), ":galtu:", None, "exact"),

            # --- "partial" (部分一致) ---
            (("疲れた", "つかれた", "疲れてる", "つかれてる", "疲れている", "つかれている"), "ひとやすみ、する？ それとも、わたしが癒してあげよっか？", None, "partial"),
            (("出勤",), responses.get_random_response('go_work'), None, "partial"),
            (("退勤", "しごおわ"), "お仕事終わったの？ お疲れさま～。 ……わたしの癒し、必要かな？ 必要なら、いつでも言ってね", None, "partial"),

            # --- "context" (前後n文字まで許容) ---
            (("眠い", "眠たい", "ねむ"), "なるほど、眠いんだね。……我慢はよくないよ？ 欲には素直にならないと", False, "context"),
            (("つらい", "つらすぎ"), "つらいときは、甘えてもいいんだよ？", None, "context"),
            (("おやすみ",), responses.get_random_response('good_night'), False, "context"),
        ]

        # 5. ループ処理 (一致モードで判定を分岐)
        for keywords, response, reply_rule, match_mode in timeline_keywords:

            # (リプライ制限のチェック)
            if reply_rule is not None:
                if reply_rule is True and not is_reply:
                    continue
                if reply_rule is False and is_reply:
                    continue

            matched = False

            if match_mode == "exact":
                # 1. 完全一致モード
                if cleaned_text in keywords:
                    matched = True

            elif match_mode == "partial":
                # 2. 部分一致モード
                if any(kw in text for kw in keywords):
                    matched = True

            elif match_mode == "context":
                # 3. "context" モード (前後の文字数をチェック)
                for kw in keywords:
                    if kw in text:
                        # キーワードが見つかったら、前後を分割
                        parts = text.split(kw, 1)
                        before = parts[0].strip(CHARS_TO_STRIP)
                        after = parts[1].strip(CHARS_TO_STRIP)
                        # 前後の文字数が上限以内かチェック
                        if len(before) <= CONTEXT_LIMIT and len(after) <= CONTEXT_LIMIT:
                            matched = True
                            # --- contextモード固有の例外処理 ---
                            # (例:「眠い」だけど「くない」が後ろにある場合は除外)
                            if keywords == ("眠い", "眠たい", "ねむ") and "くない" in after:
                                matched = False

                            if matched:
                                break  # 1つでも一致したらチェック終了

            if matched:
                # --- 確率・特殊処理 ---
                if keywords == ("にゃーん",):
                    if random.randint(1, 2) != 1:
                        continue
                if keywords == ("ぬるぽ",):
                    if random.randint(1, 3) != 1:
                        continue
                # --- 応答処理 ---
                if callable(response):
                    response = response()
                self.msk.notes_create(text=response, reply_id=note['id'], visibility=vis)
                if response == ":galtu:":
                    self.msk.notes_reactions_create(note_id=note['id'], reaction=response)
                    return
                return

        if "さんごちゃん" in text:
            if random.randint(1, 3) == 1:
                parts = text.split("さんごちゃん", 1)
                before = parts[0].strip()  # 前の文章を取得
                after = parts[1].strip()  # 後ろの文章を取得
                if before or after:
                    name = self._get_user_display_name(user_id, user)
                    self.msk.notes_create(text=f"呼んだ？ {name}さん", reply_id=note["id"], visibility=vis)
                    return

    # --- メインループ ---
    async def main_task(self):
        """ボットを起動し、WebSocketに接続する"""
        # 同期呼び出しを to_thread で非同期実行 ▼▼▼
        try:
            await asyncio.to_thread(
                self.msk.notes_create,
                text='うーん、うとうとしちゃってたみたい……？'
            )
        except Exception as e:
            print(f"起動ノートの投稿に失敗: {e}")

        # 同期呼び出しを to_thread で非同期実行 ▼▼▼
        await asyncio.to_thread(self._sync_followings)

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

                        # イベント処理を to_thread で非同期実行 ▼▼▼
                        if channel_id == "main":
                            if event_type == "followed":
                                await asyncio.to_thread(self._on_followed, event_body)
                            elif event_type == "mention":
                                await asyncio.to_thread(self._on_mention, event_body)
                        elif channel_id == "home" and event_type == "note":
                            await asyncio.to_thread(self._on_timeline_note, event_body)

            except websockets.exceptions.ConnectionClosed as e:
                print(f"[main_task] ConnectionClosed: code={e.code}, reason={e.reason}")
                await asyncio.sleep(5)
            except Exception as e:
                print("[main_task] Error:", e)
                await asyncio.sleep(5)
