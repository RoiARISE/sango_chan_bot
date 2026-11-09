"""Unit tests for ``src.stores.user_store.UserStore``.

The store owns ``data/user_data.json``: persistence, nickname sanitizing and the
one-increase-per-day intimacy rule. Each test uses a temporary file so nothing
touches the real data directory.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.stores.user_store import UserStore

JST = timezone(timedelta(hours=9))


class FakeMsk:
    """Minimal following API double for ``sync_followings``."""

    def __init__(self, pages=None):
        self.pages = pages if pages is not None else []
        self.calls = []

    def users_following(self, **kwargs):
        self.calls.append(dict(kwargs))
        if not self.pages:
            return []
        return self.pages.pop(0)


@pytest.fixture
def make_store(tmp_path):
    def factory(msk=None, filename="user_data.json"):
        store = UserStore(str(tmp_path / filename), msk or FakeMsk(), "bot-id")
        store.load()
        return store

    return factory


def test_load_missing_file_starts_empty(make_store):
    store = make_store()
    assert store.get("user-1") is None
    assert store._data == {}


def test_load_invalid_json_starts_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    store = UserStore(str(path), FakeMsk(), "bot-id")
    store.load()
    assert store._data == {}


def test_save_and_load_roundtrip(make_store, tmp_path):
    store = make_store()
    store.set_nickname("user-1", "みー", "user_1")

    reloaded = UserStore(str(tmp_path / "user_data.json"), FakeMsk(), "bot-id")
    reloaded.load()
    assert reloaded.get("user-1")["nickname"] == "みー"
    assert reloaded.get("user-1")["username"] == "user_1"


def test_ensure_user_is_idempotent(make_store):
    store = make_store()
    store.ensure_user("user-1", "user_1")
    store.set_nickname("user-1", "みー")
    store.ensure_user("user-1", "ignored")

    assert store.get("user-1")["nickname"] == "みー"
    assert store.get("user-1")["username"] == "user_1"


def test_set_and_clear_nickname(make_store):
    store = make_store()
    store.set_nickname("user-1", "みー", "user_1")
    assert store.get("user-1")["nickname"] == "みー"

    store.clear_nickname("user-1")
    assert store.get("user-1")["nickname"] == ""

    # Clearing an unknown user must not create a record.
    store.clear_nickname("missing")
    assert store.get("missing") is None


def test_remove_user(make_store):
    store = make_store()
    store.ensure_user("user-1", "user_1")
    store.remove_user("user-1")
    assert store.get("user-1") is None

    store.remove_user("missing")  # no-op


def test_display_name_prefers_nickname(make_store):
    store = make_store()
    store.set_nickname("user-1", "みー", "user_1")
    assert store.get_display_name("user-1", {"name": "表示名", "username": "user_1"}) == "みー"


def test_display_name_sanitizes_account_name(make_store):
    store = make_store()
    name = "@victim $[x2 あ] https://evil.example #tag"
    sanitized = store.get_display_name("user-1", {"name": name, "username": "user_1"})

    for marker in ("@victim", "$[", "://", "#tag"):
        assert marker not in sanitized


def test_display_name_falls_back_to_username(make_store):
    store = make_store()
    assert store.get_display_name("user-1", {"username": "user_1"}) == "user_1"
    assert store.get_display_name("user-1", {"name": "", "username": "user_1"}) == "user_1"


def test_display_name_falls_back_to_stored_username(make_store):
    store = make_store()
    store.ensure_user("user-1", "user_1")
    assert store.get_display_name("user-1") == "user_1"


def test_display_name_falls_back_to_user_id(make_store):
    store = make_store()
    assert store.get_display_name("user-1") == "user-1"


def test_profile_get_and_set(make_store):
    store = make_store()
    assert store.get_profile("user-1") == ""

    store.set_profile("user-1", "チョココーヒーが好き", "user_1")
    assert store.get_profile("user-1") == "チョココーヒーが好き"
    assert store.get("user-1")["username"] == "user_1"


def test_set_intimacy_clamps_to_range(make_store):
    store = make_store()
    store.set_intimacy("user-1", 500)
    assert store.get_intimacy("user-1") == 100
    store.set_intimacy("user-1", -500)
    assert store.get_intimacy("user-1") == -100


def test_change_intimacy_zero_is_noop(make_store):
    store = make_store()
    value, applied = store.change_intimacy("user-1", 0)
    assert (value, applied) == (0, False)


def test_change_intimacy_decrease_is_unlimited(make_store):
    store = make_store()
    assert store.change_intimacy("user-1", -5) == (-5, True)
    assert store.change_intimacy("user-1", -5) == (-10, True)


def test_change_intimacy_increase_once_per_day(make_store):
    store = make_store()
    value, applied = store.change_intimacy("user-1", 3)
    assert (value, applied) == (3, True)

    # A second increase on the same JST day is ignored.
    assert store.change_intimacy("user-1", 3) == (3, False)


def test_change_intimacy_increases_again_on_the_next_day(make_store):
    store = make_store()
    store.set_intimacy("user-1", 1)
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    store._data["user-1"]["last_intimacy_increment_date"] = yesterday

    assert store.change_intimacy("user-1", 2) == (3, True)


def test_change_intimacy_is_clamped(make_store):
    store = make_store()
    store.set_intimacy("user-1", 100)
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    store._data["user-1"]["last_intimacy_increment_date"] = yesterday
    assert store.change_intimacy("user-1", 50) == (100, True)


def test_sync_followings_adds_missing_users_and_paginates(make_store):
    first_page = [{"followee": {"id": f"u{i}", "username": f"user{i}"}} for i in range(100)]
    second_page = [{"followee": {"id": "last", "username": "last_user"}}]
    msk = FakeMsk(pages=[first_page, second_page])
    store = make_store(msk)

    store.sync_followings()

    assert store.get("u0")["username"] == "user0"
    assert store.get("u99")["username"] == "user99"
    assert store.get("last")["username"] == "last_user"
    assert len(msk.calls) == 2
    assert msk.calls[0] == {"user_id": "bot-id", "limit": 100}
    assert msk.calls[1]["untilId"] == "u99"


def test_sync_followings_does_not_overwrite_existing_records(make_store):
    msk = FakeMsk(pages=[[{"followee": {"id": "u0", "username": "new"}}]])
    store = make_store(msk)
    store.set_nickname("u0", "みー", "old")

    store.sync_followings()

    assert store.get("u0")["nickname"] == "みー"
    assert store.get("u0")["username"] == "old"


def test_sync_followings_swallows_errors(make_store):
    class BrokenMsk:
        def users_following(self, **kwargs):
            raise RuntimeError("API down")

    store = make_store(BrokenMsk())
    store.sync_followings()  # must not raise
    assert store._data == {}


def test_save_writes_utf8_json(make_store, tmp_path):
    store = make_store()
    store.set_nickname("user-1", "さんご", "user_1")

    raw = (tmp_path / "user_data.json").read_text(encoding="utf-8")
    assert "さんご" in raw
    assert json.loads(raw)["user-1"]["nickname"] == "さんご"
