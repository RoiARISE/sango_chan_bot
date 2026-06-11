import json
import logging

from misskey import Misskey

logger = logging.getLogger(__name__)


class UserStore:
    def __init__(self, filepath: str, msk: Misskey, my_id: str):
        self._filepath = filepath
        self._msk = msk
        self._my_id = my_id
        self._data: dict = {}

    def load(self) -> None:
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def save(self) -> None:
        with open(self._filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, user_id: str) -> dict | None:
        return self._data.get(user_id)

    def ensure_user(self, user_id: str, username: str) -> None:
        if user_id not in self._data:
            self._data[user_id] = {
                "nickname": "",
                "username": username,
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": ""
            }
            self.save()

    def set_nickname(self, user_id: str, nickname: str, username: str = "") -> None:
        if user_id not in self._data:
            self._data[user_id] = {
                "username": username,
                "nickname": "",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": ""
            }
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
        if record and record.get("username"):
            return record["username"]
        return user_id

    def get_profile(self, user_id: str) -> str:
        record = self._data.get(user_id)
        if record:
            return record.get("description", "")
        return ""

    def set_profile(self, user_id: str, description: str, username: str = "") -> None:
        if user_id not in self._data:
            self._data[user_id] = {
                "username": username,
                "nickname": "",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": ""
            }
        self._data[user_id]["description"] = description
        self.save()

    def get_intimacy(self, user_id: str) -> int:
        record = self._data.get(user_id)
        if record:
            return record.get("intimacy", 0)
        return 0

    def set_intimacy(self, user_id: str, value: int, username: str = "") -> None:
        if user_id not in self._data:
            self._data[user_id] = {
                "username": username,
                "nickname": "",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": ""
            }
        clamped_value = max(-100, min(100, value))
        self._data[user_id]["intimacy"] = clamped_value
        self.save()

    def change_intimacy(self, user_id: str, change: int, username: str = "") -> tuple[int, bool]:
        """親密度を増減させ、変更後の値と、上昇が実際に適用されたかどうかを返します。
        上昇は1日1回（JST基準）のみに制限されます。下降は無制限です。
        """
        if user_id not in self._data:
            self._data[user_id] = {
                "username": username,
                "nickname": "",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": ""
            }

        record = self._data[user_id]
        current_val = record.get("intimacy", 0)

        if change > 0:
            from datetime import datetime, timedelta, timezone
            JST = timezone(timedelta(hours=9))
            today_str = datetime.now(JST).strftime("%Y-%m-%d")

            last_date = record.get("last_intimacy_increment_date", "")
            if last_date == today_str:
                # 既に本日上昇済みのため、上昇を無視
                return current_val, False
            else:
                new_val = max(-100, min(100, current_val + change))
                record["intimacy"] = new_val
                record["last_intimacy_increment_date"] = today_str
                self.save()
                return new_val, True
        elif change < 0:
            new_val = max(-100, min(100, current_val + change))
            record["intimacy"] = new_val
            self.save()
            return new_val, True

        return current_val, False

    def sync_followings(self) -> None:
        """起動時にフォロー中のユーザー情報を同期する (同期関数 / asyncio.to_thread 経由で呼ぶ)"""
        try:
            added_count = 0
            until_id = None
            while True:
                kwargs = {"user_id": self._my_id, "limit": 100}
                if until_id:
                    kwargs["untilId"] = until_id
                followings = self._msk.users_following(**kwargs)
                if not followings:
                    break
                for item in followings:
                    user = item["followee"]
                    if user["id"] not in self._data:
                        self._data[user["id"]] = {
                            "nickname": "",
                            "username": user["username"],
                            "description": "",
                            "intimacy": 0,
                            "last_intimacy_increment_date": ""
                        }
                        added_count += 1
                until_id = followings[-1]["followee"]["id"]
                if len(followings) < 100:
                    break
            if added_count > 0:
                self.save()
            logger.info("フォロー同期完了: %d件のユーザーを追加しました", added_count)
        except Exception:
            logger.error("フォロー同期エラー", exc_info=True)
