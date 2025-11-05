import asyncio
import json
import websockets
import random
import threading
import time
import os
from misskey import Misskey

import utils

TOKEN = 'your_bot_token' # MisskeyのAPIトークンをここに入力
WS_URL = 'wss://example.com/streaming?i=' + TOKEN # あなたのbotの接続先URL
msk = Misskey('example.com', i=TOKEN) # Misskeyインスタンスを作成
MY_ID = msk.i()['id'] # botのユーザーIDを取得

msk.notes_create(text='うーん、うとうとしちゃってたみたい……？') # pm2等の再起動時に発する言葉。なんとなくでつけてる

ADMIN_ID = "example1234567"  # 管理者のユーザーIDを設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NICKNAME_FILE = os.path.join(BASE_DIR, "nickname.json")

MAX_NICKNAME_LENGTH = 15  # あだ名の最大文字数

# JSONロード
try:
    with open(NICKNAME_FILE, "r", encoding="utf-8") as f:
        nicknames = json.load(f)
except FileNotFoundError:
    nicknames = {}

# 自分のユーザー情報を取得
me = msk.i()
my_id = me["id"]

# フォロー一覧を取得
followings = msk.users_following(user_id=my_id, limit=100)  # 最大100件。必要に応じてページング対応も可

added = 0
for item in followings:
    # followee オブジェクトの中にユーザー情報が入っている
    user = item["followee"]
    uid = user["id"]
    username = user["username"]
    if uid not in nicknames:
        nicknames[uid] = {"nickname": "", "username": username}
        added += 1

# JSON保存
if added > 0:
    with open(NICKNAME_FILE, "w", encoding="utf-8") as f:
        json.dump(nicknames, f, ensure_ascii=False, indent=2)

print(f"✅ 起動時ロード完了: {added}件のユーザーを追加しました。") # プログラム起動時、nickname.jsonが書き込まれる

def load_data():
    try:
        with open(NICKNAME_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(data):
    with open(NICKNAME_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_data()

# ===== あだ名取得 =====
def get_name(user_id, user_data, users):
    """#登録済みならあだ名、なければ表示名→ユーザーネームの順"""
    # JSONに登録されているあだ名を優先
    if (
        user_id in users
        and "nickname" in users[user_id]
        and users[user_id]["nickname"]
    ):
        return users[user_id]["nickname"]

    # Misskey APIからのユーザー情報を使う
    if "name" in user_data and user_data["name"]:
        sanitized = utils.sanitize_nickname(user_data["name"]) # 表示名に変な文字が入っていた場合
        if utils.validate_nickname(sanitized):
            return sanitized  # ✅ 表示名があるならそちらを優先
    return user_data["username"]  # fallback

def GoWork():
      rand = random.randint(1,3)
      if rand == 1:
            return "お仕事、頑張ってきてね。わたし、帰ってくるの、待ってるから……"
      if rand == 2:
            return "お仕事は大事だけど、あんまり無理はしないでね？"
      if rand == 3:
            return "お仕事とわたし、どっちが大事なんだろう……。まぁ、わたしにはロイちゃんがいるから、いい……のかな？\n……あっ、ち、違う！ これは違くて…！ なんでもないから……！"
      
def GoodNight():
        rand = random.randint(1,3)
        if rand == 1:
            return "また朝に会おうね、おやすみ"
        if rand == 2:
            return "おやすみって言ったんだから、夜更かししようなんて考えないでね？"
        if rand == 3:
            return "寝ちゃうんだ……。ふーん……"
        
def MentionSleepy():
        rand = random.randint(1,2)
        if rand == 1:
            return "よしよし……"
        if rand == 2:
            return "……なでなで、してあげるね"
        
def ToYou():
        rand = random.randint(1,2)
        if rand == 1:
            return "変なお願いをするもんだね……"
        if rand == 2:
            return "えっと……、ど、どんな風に罵ってほしいとか、ある？"
        
def TwoTimeSleep():
        rand = random.randint(1,2)
        if rand == 1:
            return "二度寝をするのは悪いことではないけど、ほどほどにしておいてね？"
        if rand == 2:
            return "30分後にアラームを設定。……よし、準備おっけー。じゃあ、わたしも二度寝しちゃおうかな……"

def reply():
        rand = random.randint(1,4)
        if rand == 1:
            return "あっ、……呼んだ？"
        if rand == 2:
            return "えっと、……呼んだ？" 
        if rand == 3:
            return "なぁに？"
        if rand == 4:
            return "わたしが必要な感じかな？"      

def morning():
        rand = random.randint(1,2)
        if rand == 1:
            return "よく眠れたよ～。元気いーっぱい"
        if rand == 2:
            return "あんまり寝れなかったかな……。まぁ、なんとかなるでしょ～"        
        
def delayed_reply(note_id, user_id, delay=10800):
    time.sleep(delay)
    if user_id == ADMIN_ID:
        msk.notes_create(text='ロイちゃん、これやった？', renote_id=note_id)
    else:
        msk.notes_create(text='これやった？', renote_id=note_id)

# ===== メイン処理 =====
async def main_task():
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                print("Starting [main_task]")

                # --- 各チャンネル購読 ---
                await ws.send(json.dumps({
                    "type": "connect",
                    "body": {
                        "channel": "main",
                        "id": "main_channel"
                    }
                }))
                await ws.send(json.dumps({
                    "type": "connect",
                    "body": {
                        "channel": "homeTimeline",
                        "id": "home_channel"
                    }
                }))
                print("[main_task] Subscribed to main and homeTimeline")

                # keep_aliveを同一接続で動かす
                asyncio.create_task(keep_alive(ws))

                while True:
                    data = json.loads(await ws.recv())

                    if data.get("type") == "channel":
                        channel_id = data["body"].get("id")
                        inner = data["body"]

                        # === main_channelのイベント ===
                        if channel_id == "main_channel":
                            if inner["type"] == "followed":
                                user = inner["body"]
                                await on_follow(user)
                            elif inner["type"] == "mention":
                                note = inner["body"]
                                await followback(note)

                        # === home_channelのイベント ===
                        elif channel_id == "home_channel":
                            if inner["type"] == "note":
                                note = inner["body"]
                                await on_note(note)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[main_task] ConnectionClosed: code={e.code}, reason={e.reason}")
            await asyncio.sleep(5)
        except Exception as e:
            print("[main_task] Error:", e)
            await asyncio.sleep(5)


# ===== 旧runner_taskの内容を内包したため空のダミーとして残す。なんかAI様がそう言ってたのでなんとなく残してる =====
async def runner_task():
    """[runner_task] は main_task に統合済み。"""
    print("[runner_task] is now integrated into main_task.")
    while True:
        await asyncio.sleep(3600)


# ===== Pingを同一接続内で定期的に送るという、無理くりなやり口 =====
async def keep_alive(ws):
    while True:
        try:
            await asyncio.sleep(600)
            await ws.send(json.dumps({"type": "ping"}))
            #print("[keep_alive] Sent ping")
        except Exception as e:
            print("[keep_alive] Ping error:", e)
            break

async def on_follow(user):
    # ここでは何もしない（メンションで指示されたら後記の「followback(note)」が対応）
    try:
        userid = user['username'] # ユーザーのID(@user_id)を取得
        host = user.get('host') # ユーザーのホスト名(@example.com)を取得
        #user_id = user["id"] # ダイレクト投稿で宛先を指定するときに必要(これが何なのかは分かってない)

        if host:
            mention = f"@{userid}@{host}" # リモートユーザーなら「@user_id@example.com」と表示されるはず
        else:
            mention = f"@{userid}" # ローカルユーザーなら「@user_id」とだけ表示されるはず
            #なぜかこのように分けないとうまく動かなかった
        msk.notes_create(text=f"フォローありがとうございます、{mention}さん\n「フォローして」とメンションしながら投稿すると、フォローバックするよ") #  ,visibility="home", specified ,visible_user_ids=[user_id] 投稿範囲指定やダイレクト投稿をする際に使ったやつ
        print(f"フォローされました: {mention}")    
    
    except Exception as e:
        print(f"フォロー処理エラー: {e}")


async def followback(note):
    try:
        # まずユーザー情報を取得して、自分がフォローしてるか確認
        user = note['user']
        relation = msk.users_show(user_id=user['id']) # ユーザーの情報を見る
        mentioner = msk.users_show(user_id=note['userId']) 
        username = mentioner['name'] or mentioner['username'] # 「mentioner」と「username」はメンションしてきたユーザーの名前を取得してそれで呼ぶやつ
        userid = user['username'] # ユーザーのID(@user_id)を取得
        host = user.get('host') # ユーザーのホスト名(@example.com)を取得
        
        if host:
            mention = f"@{userid}@{host}" # リモートユーザーなら「@user_id@example.com」と表示されるはず
        else:
            mention = f"@{userid}" # ローカルユーザーなら「@user_id」とだけ表示されるはず
            #なぜかこのように分けないとうまく動かなかった
        if "フォローして" in note['text'] in note['text']: 
            if not relation.get('isFollowed'):
                msk.notes_create(text="……だれ？", reply_id=note['id']) # フォローしてない人からの「フォローして」を拒否するやつ
                return

            if relation.get('isFollowing'): # すでにフォローしてる場合
                print(f"{username} さんはフォロー済みです")
                msk.notes_create(text=f"{mention} {username}さん、もうフォローしてるよー", reply_id=note['id'])
            else:
                user_id = user['id']       # JSONでのキーに使う安全な識別子
                if user_id not in nicknames:
                    nicknames[user_id] = {"nickname": "", "username": userid}
                    save_data(nicknames)
                print(f"JSONに {username}({userid}) さんを登録しました")                
                print(f"{username} さんをフォローします")
                msk.following_create(user['id']) # 未フォローの場合
                msk.notes_create(text=f'{mention} フォローバックしたよ、{username}さん。これからよろしくね', reply_id=note['id'])

        elif "フォロー解除して" in note['text']: # 自動フォロー解除はできなかったので致し方なし実装
            if relation.get('isFollowing'): # フォローしてる場合
                print(f"{username} さんのフォローを解除します")
                msk.notes_create(text=f'{mention} さよなら、になっちゃうのかな……', reply_id=note['id'])
                await asyncio.sleep(10) # あえて10秒待ってフォロー解除(意味はない)
                msk.following_delete(user['id'])
                print(f"{username} さんのフォローを解除しました")
            else:
                print(f"{username} さんをフォローしていません") # 未フォローの場合
                msk.notes_create(text=f"{mention} もともとフォローしてないよー", reply_id=note['id'])

    except Exception as e:
        print(f"メンション処理エラー: {e}")

async def on_note(note):
    if note["text"] is None: #空白ノートを無視
        return
    if note['renoteId']: #引用を無視
        return
    if note["user"]["id"] == MY_ID: #連鎖反応事故防止
        return

    text = note.get("text", "")
    user = note['user']
    userid = user['username'] # ユーザーのID(@user_id)を取得
    host = user.get('host') # ユーザーのホスト名(@example.com)を取得
    user = note["user"]["username"]
    vis = note.get("visibility", "public")

    if host:
        user_mention = f"@{userid}@{host}" # リモートユーザーなら「@user_id@example.com」と表示されるはず
    else:
        user_mention = f"@{userid}" # ローカルユーザーなら「@user_id」とだけ表示されるはず

    match = re.search(r"(\d+)d(\d+)", text.lower())

    if note.get('mentions'): # メンションされるかつ同じワードが含まれているときに返信するやつ
        if MY_ID in note['mentions']:
            if "はじめまして" in note['text']:
                msk.notes_create(text='はじめまして、わたしを見つけてくれてありがとう。これからよろしくね', reply_id=note['id'], visibility=vis)
                return
            if "こんにちは" in note['text']:
                msk.notes_create(text='こんにちは、どうしたの？', reply_id=note['id'], visibility=vis)
                return
            if "自己紹介" in note['text'] or "あなたは？" in note['text']:
                msk.notes_create(text='わたしはここ「3.5Mbps.net」の看板娘、さんごです。……看板娘は自称だけどね\nあなたのことも、さんごに教えて欲しいな', reply_id=note['id'], visibility=vis)
                return
            if "よしよし" in note['text'] or "なでなで" in note['text']:
                msk.notes_create(text="わたしの頭なんか撫でて、楽しい？ えっと、あなたが喜んでくれるなら、いいんだけど……", reply_id=note['id'], visibility=vis)
                return
            if "にゃーん" in note['text']:
                msk.notes_create(text="にゃ〜ん", reply_id=note['id'], visibility=vis)
                return
            if "今何時" in note['text'] or "いまなんじ" in note['text'] and not note['replyId']:
                from datetime import datetime
                now = datetime.now()
                msk.notes_create(text=f'いまは {now.hour}:{now.minute}:{now.second} だよ。どうしたの……？ 時計を見る元気もない感じかな？', reply_id=note['id'], visibility=vis)
                return
            if "罵って" in note['text']:
                msk.notes_create(text=ToYou(), reply_id=note['id'], visibility=vis)
                return
            if "さんごちゃーん" in note['text'] or "さんごちゃ〜ん" in note['text']:
                await asyncio.sleep(1)
                msk.notes_create(text='は〜い', reply_id=note['id'], visibility=vis)
                return
            if "何が好き？" in note['text'] and note['replyId']:
                await asyncio.sleep(1)
                msk.notes_create(text='チョココーヒー よりもあ・な・た♪', reply_id=note['id'], visibility=vis)
                await asyncio.sleep(10)
                msk.notes_create(text='さっきのなに……？')
                return
            if "ちくわ大明神" in note['text'] and note['replyId']:
                msk.notes_create(text='…なに？', reply_id=note['id'], visibility=vis)
                return
            if "ping" in note['text']:
                msk.notes_create(text='pong？', reply_id=note['id'], visibility=vis)
                return
            if "回線速度計測" in note['text']: # 現在接続しているインターネットの回線速度を計測する機能
                if note["user"]["id"] == ADMIN_ID: # プロフィールから「RAW」を開いて、「ID」の部分をコピーして貼り付ける。これを設定すると機能を自分専用にできる
                    import speedtest 
                    msk.notes_create(text="了解。じゃあ計測してくるね", reply_id=note['id'])
                    st = speedtest.Speedtest()
                    st.get_best_server()
                    download_speed = st.download() / 1024 / 1024  # Mbpsに変換
                    upload_speed = st.upload() / 1024 / 1024  # Mbpsに変換
                    ping = st.results.ping
                    speed_result =f"計測かんりょー。下り{download_speed:.2f}Mbps、上り{upload_speed:.2f}Mbps、ping値{ping:.2f}msだったよ。……これは速いって言えるのかな？"
                    msk.notes_create(text=speed_result, renote_id=note['id'])
                    return
                else:
                    msk.notes_create(text="この機能は使える人が限られてるんだ。ゴメンね", reply_id=note['id'])
                    return 
                    
            if "todo" in note['text']:
                print("todoを検知")
                # noteのidとuser_idをスレッドに渡す
                threading.Thread(
                    target=delayed_reply,
                    args=(note["id"], note["user"]["id"], 10800), # 3時間後に実行
                    daemon=True
                ).start()
                return  
            
            if "って呼んで" in note['text'] or "と呼んで" in note['text']:
                users = load_data()
                user_id = note["user"]["id"]
                text = note.get("text", "")
                nickname = utils.extract_nickname(text)
                if nickname:
                    # 文字数チェックはサニタイズ前に実行
                    if len(nickname) > MAX_NICKNAME_LENGTH:
                        msk.notes_create(text=f"えぇっと、その名前はちょっと長いかも……\n15文字以内にしてほしいな", reply_id=note["id"])
                        return
                    sanitized = utils.sanitize_nickname(nickname)
                    if utils.validate_nickname(sanitized):
                        users[user_id]["nickname"] = sanitized
                        save_data(users)
                        msk.notes_create(text=f"わかった。これからは{sanitized}さんって呼ぶね\nこれからもよろしくね、{sanitized}さん", reply_id=note["id"])
                    else:
                        msk.notes_create(text=f"えぇっと、その名前はちょっと……だめかも……", reply_id=note["id"])
                    return
                
            if "呼び名を忘れて" in note['text'] or "あだ名を消して" in note['text']:
                users = load_data()
                user_id = note["user"]["id"]
                mentioner = msk.users_show(user_id=note['userId']) 
                username = mentioner['name'] or mentioner['username']
                if user_id in users and users[user_id].get("nickname"):
                    users[user_id]["nickname"] = ""
                    save_data(users)
                    msk.notes_create(
                        text=f"うん、呼び名は忘れたよ。これからは普通に{username}さんって呼ぶね",
                        reply_id=note["id"]
                    )
                else:
                    msk.notes_create(text=f"もともと特別な呼び名は登録されていないみたいだよ", reply_id=note["id"])
                return

            if "さんごちゃん？" in note['text']:
                users = load_data()
                user_id = note["user"]["id"]
                mentioner = msk.users_show(user_id=note['userId']) 
                name = get_name(user_id, mentioner, users)
                msk.notes_create(text=f"どうしたの？ {name}さん", reply_id=note['id'], visibility=vis)
                return
            

            if not match:
                return
            count, sides = match.groups()
            rolls = roll_dice(count, sides)

            if not rolls:
                return
           # 出力：1個ならその数値、複数ならカンマ区切り
            if len(rolls) == 1:
                reply = f"{rolls[0]} だよ"
            else:
                reply = f"{', '.join(map(str, rolls))} だよ"

            msk.notes_create(reply_id=note["id"],text=f"{user_mention} {reply}")
            

    else:
            if "眠い" in note['text'] or "眠たい" in note['text'] or "ねむ" in note['text'] and "くない" not in note['text'] and not note['replyId']: # ノートに特定のワードが含まれていたら
                msk.notes_create(text='なるほど、眠いんだね。……我慢はよくないよ？ 欲には素直にならないと', reply_id=note['id']) # 返信する
                return
            if "つらい" in note['text'] or "つらすぎ" in note['text']:
                msk.notes_create(text='つらいときは、甘えてもいいんだよ？', reply_id=note['id'])
                return
            if "疲れた" in note['text'] or "つかれた" in note['text'] or "疲れてる" in note['text'] or "つかれてる" in note['text'] or "疲れている" in note['text'] or "つかれている" in note['text']:
                msk.notes_create(text='ひとやすみ、する？ それとも、わたしが癒してあげよっか？', reply_id=note['id']) 
                return
            if "おはよ" in note['text'] and not note['replyId']:
                msk.notes_create(text="おはよ、よく眠れた？ わたしは"+morning()+"", reply_id=note['id'])
                    return
            if 'おやすみ' in note['text'] and 'すきー' not in note['text'] and not note['replyId']: 
                    msk.notes_create(text=GoodNight(), reply_id=note['id'])
                    return  
            if "おそよ" in note['text'] and not note['replyId']:
                msk.notes_create(text='遅いよ、ねぼすけさん。なんで寝坊したのか、ちゃんと説明して？', reply_id=note['id'])
                return
            if "出勤" in note ['text']:
                msk.notes_create(text=GoWork(), reply_id=note['id'])
                return
            if "退勤" in note['text'] or "しごおわ" in note ['text']:
                msk.notes_create(text='お仕事終わったの？ お疲れさま～。 ……わたしの癒し、必要かな？ 必要なら、いつでも言ってね', reply_id=note['id'])
                return
            if "にゃーん" in note ['text'] and not note['replyId']:
                if random.randint(1,2) == 1:
                    msk.notes_create(text='にゃーん。……えへへ、わたしも混ぜて？', reply_id=note['id'])
                    return
            if "二度寝" in note ['text'] and not note['replyId']:
                msk.notes_create(text=TwoTimeSleep(), reply_id=note['id'])
                return
            if "ぬるぽ" in note['text']:
                if random.randint(1,3) == 1:
                    msk.notes_reactions_create(note_id=note['id'], reaction=":galtu:")
                    return
            if "さんごちゃん" in note['text']:
                if random.randint(1,3) == 1:
                    users = load_data()
                    user_id = note["user"]["id"]
                    mentioner = msk.users_show(user_id=note['userId']) 
                    name = get_name(user_id, mentioner, users)
                    after = note['text'].split("さんごちゃん", 1)[1].strip() # 「さんごちゃん」以降になにか文字があると反応するやつ。確率は3分の1
                    if after:
                        # 実際の返信処理
                        msk.notes_create(text=f"呼んだ？ {name}さん", reply_id=note["id"])
                        return

# ===== 実行部 =====
async def main():
    await main_task()

if __name__ == "__main__":
    asyncio.run(main())
