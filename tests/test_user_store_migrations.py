"""Tests for the SQLite schema migrations and the legacy JSON importer."""

from __future__ import annotations

import json
import sqlite3

from src.stores.user_store import UserStore


class FakeMsk:
    def users_following(self, **kwargs):
        return []


def write_legacy_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_load_creates_schema_and_records_migrations(tmp_path):
    db_path = tmp_path / "user_data.sqlite3"
    store = UserStore(str(db_path), FakeMsk(), "bot-id")
    store.load()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]

    assert {"users", "schema_migrations"} <= tables
    assert versions == [1, 2, 3]


def test_load_imports_legacy_json_and_marks_it_migrated(tmp_path):
    json_path = tmp_path / "user_data.json"
    db_path = tmp_path / "user_data.sqlite3"
    legacy = {
        "user-1": {
            "username": "user_1",
            "nickname": "みー",
            "description": "チョコ好き",
            "intimacy": 12,
            "last_intimacy_increment_date": "2026-01-01",
        },
        "user-2": {
            "username": "user_2",
            "nickname": "",
            "description": "",
            "intimacy": -3,
            "last_intimacy_increment_date": "",
        },
    }
    write_legacy_json(json_path, legacy)

    store = UserStore(str(db_path), FakeMsk(), "bot-id", json_path=str(json_path))
    store.load()

    assert store.get("user-1") == {
        "username": "user_1",
        "nickname": "みー",
        "description": "チョコ好き",
        "intimacy": 12,
        "last_intimacy_increment_date": "2026-01-01",
    }
    assert store.get("user-2")["intimacy"] == -3

    migrated = read_json(json_path)
    assert migrated["migrated"] is True
    # The original records are preserved in the JSON file.
    assert migrated["user-1"]["nickname"] == "みー"


def test_migration_is_idempotent_across_reloads(tmp_path):
    json_path = tmp_path / "user_data.json"
    db_path = tmp_path / "user_data.sqlite3"
    write_legacy_json(
        json_path,
        {
            "user-1": {
                "username": "user_1",
                "nickname": "みー",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": "",
            }
        },
    )

    store = UserStore(str(db_path), FakeMsk(), "bot-id", json_path=str(json_path))
    store.load()
    store.set_nickname("user-1", "さんご")
    store.close()

    reloaded = UserStore(
        str(db_path), FakeMsk(), "bot-id", json_path=str(json_path)
    )
    reloaded.load()

    assert reloaded.user_ids() == ["user-1"]
    # Re-running the importer must not restore the old JSON nickname.
    assert reloaded.get("user-1")["nickname"] == "さんご"


def test_json_already_marked_migrated_is_not_imported(tmp_path):
    json_path = tmp_path / "user_data.json"
    db_path = tmp_path / "user_data.sqlite3"
    write_legacy_json(
        json_path,
        {
            "user-1": {
                "username": "user_1",
                "nickname": "みー",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": "",
            },
            "migrated": True,
        },
    )

    store = UserStore(str(db_path), FakeMsk(), "bot-id", json_path=str(json_path))
    store.load()

    assert store.user_ids() == []
    # The marker is left untouched.
    assert read_json(json_path)["migrated"] is True


def test_invalid_legacy_json_does_not_crash_or_mark(tmp_path):
    json_path = tmp_path / "user_data.json"
    db_path = tmp_path / "user_data.sqlite3"
    json_path.write_text("{not json", encoding="utf-8")

    store = UserStore(str(db_path), FakeMsk(), "bot-id", json_path=str(json_path))
    store.load()

    assert store.user_ids() == []
    assert json_path.read_text(encoding="utf-8") == "{not json"


def test_json_path_is_derived_for_backwards_compatibility(tmp_path):
    json_path = tmp_path / "user_data.json"
    write_legacy_json(
        json_path,
        {
            "user-1": {
                "username": "user_1",
                "nickname": "みー",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": "",
            }
        },
    )

    # Passing the legacy JSON path should place the database next to it.
    store = UserStore(str(json_path), FakeMsk(), "bot-id")
    store.load()

    assert (tmp_path / "user_data.sqlite3").exists()
    assert store.get("user-1")["nickname"] == "みー"
    assert read_json(json_path)["migrated"] is True


def test_writes_after_migration_only_touch_the_database(tmp_path):
    json_path = tmp_path / "user_data.json"
    db_path = tmp_path / "user_data.sqlite3"
    write_legacy_json(
        json_path,
        {
            "user-1": {
                "username": "user_1",
                "nickname": "",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": "",
            }
        },
    )

    store = UserStore(str(db_path), FakeMsk(), "bot-id", json_path=str(json_path))
    store.load()
    store.set_nickname("user-1", "さんご", "user_1")
    store.set_profile("user-1", "チョコ好き", "user_1")

    assert read_json(json_path)["user-1"]["nickname"] == ""
    assert read_json(json_path)["user-1"]["description"] == ""

    reloaded = UserStore(
        str(db_path), FakeMsk(), "bot-id", json_path=str(json_path)
    )
    reloaded.load()
    assert reloaded.get("user-1")["nickname"] == "さんご"
    assert reloaded.get("user-1")["description"] == "チョコ好き"


def test_migration_does_not_overwrite_existing_database_rows(tmp_path):
    json_path = tmp_path / "user_data.json"
    db_path = tmp_path / "user_data.sqlite3"
    write_legacy_json(
        json_path,
        {
            "user-1": {
                "username": "from_json",
                "nickname": "JSONの名前",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": "",
            }
        },
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                nickname TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                intimacy INTEGER NOT NULL DEFAULT 0,
                last_intimacy_increment_date TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO users (id, username, nickname) VALUES (?, ?, ?)",
            ("user-1", "from_db", "DBの名前"),
        )
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (1, 'create_users_table', '2026-01-01T00:00:00+00:00')"
        )

    store = UserStore(str(db_path), FakeMsk(), "bot-id", json_path=str(json_path))
    store.load()

    assert store.get("user-1")["username"] == "from_db"
    assert store.get("user-1")["nickname"] == "DBの名前"


def test_legacy_json_nickname_is_sanitized_on_import(tmp_path):
    json_path = tmp_path / "user_data.json"
    db_path = tmp_path / "user_data.sqlite3"
    write_legacy_json(
        json_path,
        {
            "user-1": {
                "username": "user_1",
                "nickname": "@victim $[x2 あ] https://evil.example #tag",
                "description": "",
                "intimacy": 0,
                "last_intimacy_increment_date": "",
            }
        },
    )

    store = UserStore(str(db_path), FakeMsk(), "bot-id", json_path=str(json_path))
    store.load()

    stored = store.get("user-1")["nickname"]
    for marker in ("@victim", "$[", "://", "#tag"):
        assert marker not in stored
    assert "@victim" not in store.get_display_name("user-1", {})


def test_migration_sanitizes_existing_nicknames(tmp_path):
    db_path = tmp_path / "user_data.sqlite3"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                nickname TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                intimacy INTEGER NOT NULL DEFAULT 0,
                last_intimacy_increment_date TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO users (id, username, nickname) VALUES (?, ?, ?)",
            ("user-1", "user_1", "@victim $[x2 あ]"),
        )
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            [
                (1, "create_users_table", "2026-01-01T00:00:00+00:00"),
                (2, "import_legacy_json", "2026-01-01T00:00:00+00:00"),
            ],
        )

    store = UserStore(str(db_path), FakeMsk(), "bot-id")
    store.load()

    stored = store.get("user-1")["nickname"]
    for marker in ("@victim", "$["):
        assert marker not in stored
