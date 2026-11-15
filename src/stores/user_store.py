import json
import logging
import os
import sqlite3
import threading

from misskey import Misskey

from .. import clock
from ..utils import sanitize_nickname
from .migrations import Migration, run_migrations

logger = logging.getLogger(__name__)

MIN_INTIMACY = -100
MAX_INTIMACY = 100


def _clamp_intimacy(value: int) -> int:
    return max(MIN_INTIMACY, min(MAX_INTIMACY, value))


def _create_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            nickname TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            intimacy INTEGER NOT NULL DEFAULT 0,
            last_intimacy_increment_date TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _sanitize_nicknames(conn: sqlite3.Connection) -> None:
    """既存行のニックネームにもサニタイザを適用する（冪等）。"""
    for user_id, nickname in conn.execute("SELECT id, nickname FROM users"):
        if not nickname:
            continue
        sanitized = sanitize_nickname(str(nickname))
        if sanitized != nickname:
            conn.execute(
                "UPDATE users SET nickname = ? WHERE id = ?", (sanitized, user_id)
            )


def _coerce_intimacy(value: object) -> int:
    try:
        return _clamp_intimacy(int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class UserStore:
    def __init__(
        self,
        filepath: str,
        msk: Misskey,
        my_id: str,
        json_path: str | None = None,
    ):
        # 互換性のため、従来のJSONパスが渡された場合は隣にSQLiteファイルを作る。
        if json_path is None and filepath.endswith(".json"):
            json_path = filepath
            filepath = f"{filepath[:-5]}.sqlite3"

        self._db_path = filepath
        self._json_path = json_path
        self._msk = msk
        self._my_id = my_id
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def load(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

            self._ensure_parent_directory()

            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                run_migrations(conn, self._migrations())
                self._mark_legacy_json_migrated()
            except Exception:
                conn.close()
                raise

            self._conn = conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def save(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.commit()

    def _ensure_parent_directory(self) -> None:
        if self._db_path == ":memory:":
            return
        parent = os.path.dirname(os.path.abspath(self._db_path))
        os.makedirs(parent, exist_ok=True)

    def _migrations(self) -> list[Migration]:
        return [
            Migration(1, "create_users_table", _create_users_table),
            Migration(2, "import_legacy_json", self._import_legacy_json),
            Migration(3, "sanitize_nicknames", _sanitize_nicknames),
        ]

    def _read_legacy_json(self) -> dict | None:
        if not self._json_path:
            return None

        try:
            with open(self._json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "レガシーJSONを読み込めませんでした: %s", self._json_path, exc_info=True
            )
            return None

        if not isinstance(data, dict):
            logger.warning(
                "レガシーJSONの形式が不正です (オブジェクトではありません): %s",
                self._json_path,
            )
            return None

        return data

    def _import_legacy_json(self, conn: sqlite3.Connection) -> None:
        data = self._read_legacy_json()
        if data is None or data.get("migrated") is True:
            return

        inserted = 0
        for user_id, record in data.items():
            if user_id == "migrated" or not isinstance(record, dict):
                continue

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO users (
                    id,
                    username,
                    nickname,
                    description,
                    intimacy,
                    last_intimacy_increment_date
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    record.get("username") or "",
                    sanitize_nickname(str(record.get("nickname") or "")),
                    record.get("description") or "",
                    _coerce_intimacy(record.get("intimacy", 0)),
                    record.get("last_intimacy_increment_date") or "",
                ),
            )
            inserted += cursor.rowcount

        logger.info("レガシーJSONから%d件のユーザーを移行しました", inserted)

    def _mark_legacy_json_migrated(self) -> None:
        data = self._read_legacy_json()
        if data is None or data.get("migrated") is True:
            return

        data["migrated"] = True
        try:
            parent = os.path.dirname(os.path.abspath(self._json_path))
            os.makedirs(parent, exist_ok=True)
            tmp_path = f"{self._json_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._json_path)
        except OSError:
            logger.error(
                "レガシーJSONの移行状態を書き込めませんでした: %s",
                self._json_path,
                exc_info=True,
            )

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.load()
        assert self._conn is not None
        return self._conn

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> dict:
        return {
            "username": row["username"],
            "nickname": row["nickname"],
            "description": row["description"],
            "intimacy": row["intimacy"],
            "last_intimacy_increment_date": row["last_intimacy_increment_date"],
        }

    def get(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._require_conn().execute(
                """
                SELECT username, nickname, description, intimacy,
                       last_intimacy_increment_date
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return self._record_from_row(row) if row else None

    def user_ids(self) -> list[str]:
        with self._lock:
            rows = self._require_conn().execute(
                "SELECT id FROM users ORDER BY rowid"
            ).fetchall()
        return [row["id"] for row in rows]

    def ensure_user(self, user_id: str, username: str) -> None:
        with self._lock:
            conn = self._require_conn()
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)",
                    (user_id, username),
                )

    def set_nickname(self, user_id: str, nickname: str, username: str = "") -> None:
        with self._lock:
            conn = self._require_conn()
            with conn:
                conn.execute(
                    """
                    INSERT INTO users (id, username, nickname)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET nickname = excluded.nickname
                    """,
                    (user_id, username, nickname),
                )

    def clear_nickname(self, user_id: str) -> None:
        with self._lock:
            conn = self._require_conn()
            with conn:
                conn.execute(
                    "UPDATE users SET nickname = '' WHERE id = ?", (user_id,)
                )

    def remove_user(self, user_id: str) -> None:
        with self._lock:
            conn = self._require_conn()
            with conn:
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def get_display_name(self, user_id: str, user_data: dict | None = None) -> str:
        record = self.get(user_id)
        if record and record.get("nickname"):
            return sanitize_nickname(str(record["nickname"]))
        if user_data and user_data.get("name"):
            return sanitize_nickname(user_data["name"])
        if user_data and user_data.get("username"):
            return user_data["username"]
        if record and record.get("username"):
            return record["username"]
        return user_id

    def get_profile(self, user_id: str) -> str:
        record = self.get(user_id)
        if record:
            return record.get("description", "")
        return ""

    def set_profile(self, user_id: str, description: str, username: str = "") -> None:
        with self._lock:
            conn = self._require_conn()
            with conn:
                conn.execute(
                    """
                    INSERT INTO users (id, username, description)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET description = excluded.description
                    """,
                    (user_id, username, description),
                )

    def get_intimacy(self, user_id: str) -> int:
        record = self.get(user_id)
        if record:
            return record.get("intimacy", 0)
        return 0

    def change_intimacy(self, user_id: str, change: int, username: str = "") -> tuple[int, bool]:
        """親密度を増減させ、変更後の値と、上昇が実際に適用されたかどうかを返します。
        上昇は1日1回（実行環境のタイムゾーン基準）のみに制限されます。下降は無制限です。
        """
        with self._lock:
            conn = self._require_conn()
            with conn:
                row = conn.execute(
                    """
                    SELECT intimacy, last_intimacy_increment_date
                    FROM users WHERE id = ?
                    """,
                    (user_id,),
                ).fetchone()

                if row is None:
                    conn.execute(
                        "INSERT INTO users (id, username) VALUES (?, ?)",
                        (user_id, username),
                    )
                    current_val = 0
                    last_date = ""
                else:
                    current_val = row["intimacy"]
                    last_date = row["last_intimacy_increment_date"]

                if change > 0:
                    today_str = clock.today()
                    if last_date == today_str:
                        # 既に本日上昇済みのため、上昇を無視
                        return current_val, False

                    new_val = _clamp_intimacy(current_val + change)
                    conn.execute(
                        """
                        UPDATE users
                        SET intimacy = ?, last_intimacy_increment_date = ?
                        WHERE id = ?
                        """,
                        (new_val, today_str, user_id),
                    )
                    return new_val, True

                if change < 0:
                    new_val = _clamp_intimacy(current_val + change)
                    conn.execute(
                        "UPDATE users SET intimacy = ? WHERE id = ?",
                        (new_val, user_id),
                    )
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

                with self._lock:
                    conn = self._require_conn()
                    with conn:
                        for item in followings:
                            user = item["followee"]
                            cursor = conn.execute(
                                """
                                INSERT OR IGNORE INTO users (id, username)
                                VALUES (?, ?)
                                """,
                                (user["id"], user["username"]),
                            )
                            added_count += cursor.rowcount

                until_id = followings[-1]["followee"]["id"]
                if len(followings) < 100:
                    break

            logger.info("フォロー同期完了: %d件のユーザーを追加しました", added_count)
        except Exception:
            logger.error("フォロー同期エラー", exc_info=True)
