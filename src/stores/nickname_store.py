import json

from misskey import Misskey


class NicknameStore:
    def __init__(self, filepath: str, msk: Misskey, my_id: str):
        self._filepath = filepath
        self._msk = msk
        self._my_id = my_id
        self._data: dict = {}

    def load(self) -> None:
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except FileNotFoundError:
            self._data = {}

    def save(self) -> None:
        with open(self._filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, user_id: str) -> dict | None:
        return self._data.get(user_id)

    def ensure_user(self, user_id: str, username: str) -> None:
        if user_id not in self._data:
            self._data[user_id] = {"nickname": "", "username": username}
            self.save()

    def set_nickname(self, user_id: str, nickname: str, username: str = "") -> None:
        if user_id not in self._data:
            self._data[user_id] = {"username": username}
        self._data[user_id]["nickname"] = nickname
        self.save()

    def clear_nickname(self, user_id: str) -> None:
        if user_id in self._data:
            self._data[user_id]["nickname"] = ""
            self.save()

    def remove_user(self, user_id: str) -> None:
        if user_id in self._data:
            del self._data[user_id]
            self.save()

    def get_display_name(self, user_id: str, user_data: dict | None = None) -> str:
        record = self._data.get(user_id)
        if record and record.get("nickname"):
            return record["nickname"]
        if user_data and user_data.get("name"):
            return user_data["name"]
        if user_data and user_data.get("username"):
            return user_data["username"]
        return user_id

    def sync_followings(self) -> None:
        """起動時にフォロー中のユーザー情報を同期する (同期関数 / asyncio.to_thread 経由で呼ぶ)"""
        try:
            followings = self._msk.users_following(user_id=self._my_id, limit=100)
            added_count = 0
            for item in followings:
                user = item["followee"]
                if user["id"] not in self._data:
                    self._data[user["id"]] = {"nickname": "", "username": user["username"]}
                    added_count += 1
            if added_count > 0:
                self.save()
            print(f"✅フォロー同期完了: {added_count}件のユーザーを追加しました。")
        except Exception as e:
            print(f"フォロー同期エラー: {e}")
