"""Shared fakes and helpers for the regression tests."""

from __future__ import annotations

import asyncio


class FakeMisskey:
    """Synchronous Misskey client double.

    All API calls are recorded in ``calls``. ``asyncio.to_thread`` executes
    these methods in a worker thread, so they stay synchronous.
    """

    def __init__(
        self,
        my_id: str = "bot-id",
        relation: dict | None = None,
        parent_note: dict | None = None,
    ):
        self.my_id = my_id
        self.relation = relation if relation is not None else {
            "isFollowing": True,
            "isFollowed": True,
        }
        self.parent_note = parent_note or {}
        self.relations: list[dict] = []
        self.followings: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    # --- account ---------------------------------------------------------
    def i(self):
        return {"id": self.my_id}

    # --- notes -----------------------------------------------------------
    def notes_create(self, **params):
        self.calls.append(("notes_create", dict(params)))
        index = sum(1 for name, _ in self.calls if name == "notes_create")
        return {"createdNote": {"id": f"created-{index}"}}

    def notes_show(self, note_id):
        self.calls.append(("notes_show", {"note_id": note_id}))
        return dict(self.parent_note)

    # --- users / relations ----------------------------------------------
    def users_show(self, user_id):
        self.calls.append(("users_show", {"user_id": user_id}))
        return dict(self.relation)

    def users_relation(self, user_id):
        self.calls.append(("users_relation", {"user_id": user_id}))
        return self.relations

    def users_following(self, **kwargs):
        self.calls.append(("users_following", dict(kwargs)))
        return self.followings

    def following_create(self, **kwargs):
        self.calls.append(("following_create", dict(kwargs)))
        return {}

    def following_delete(self, **kwargs):
        self.calls.append(("following_delete", dict(kwargs)))
        return {}

    # --- reactions -------------------------------------------------------
    def notes_reactions_create(self, **kwargs):
        self.calls.append(("notes_reactions_create", dict(kwargs)))
        return {}

    def notes_reactions_delete(self, **kwargs):
        self.calls.append(("notes_reactions_delete", dict(kwargs)))
        return {}

    # --- helpers ---------------------------------------------------------
    def created_notes(self) -> list[dict]:
        return [params for name, params in self.calls if name == "notes_create"]

    def clear(self) -> None:
        self.calls.clear()


def note(
    *,
    nid: str = "note-1",
    user_id: str = "user-1",
    text: str = "hello",
    visibility: str = "public",
    name: str | None = None,
    **extra,
) -> dict:
    user = {"id": user_id, "username": f"user_{user_id}"}
    if name is not None:
        user["name"] = name
    data = {
        "id": nid,
        "userId": user_id,
        "text": text,
        "visibility": visibility,
        "user": user,
    }
    data.update(extra)
    return data


async def wait_until(predicate, *, timeout: float = 2.0) -> bool:
    """Yield control until predicate() is truthy or timeout elapses."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return bool(predicate())
