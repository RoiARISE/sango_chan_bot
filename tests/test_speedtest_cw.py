"""Regression test: speedtest notes must keep the command's CW.

``_handle_speedtest`` builds its ``notes_create`` parameters by hand instead of
going through ``_get_reply_kwargs``.  It copied visibility but dropped ``cw``,
so a content-warning-protected command got a result note without the warning.
"""

from __future__ import annotations

import pytest

import fakes
import src.handlers.mention as mention

CW = "ネタバレを含みます"


@pytest.fixture
def fast_speedtest(monkeypatch):
    async def fake_speedtest():
        return "計測かんりょー。下り1.00Mbps、上り1.00Mbps、ping値1.00msだったよ。"

    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr(mention.speedtest, "run_speedtest", fake_speedtest)
    monkeypatch.setattr(mention.asyncio, "sleep", fast_sleep)


async def test_speedtest_notes_keep_cw(handler, msk, fast_speedtest):
    command = fakes.note(
        nid="admin-cw-command",
        user_id="admin-id",
        text="@bot 回線速度を計測して",
        cw=CW,
    )

    await handler._handle_speedtest(command)

    created = msk.created_notes()
    assert created, "速度計測のノートが投稿されていない"
    missing = [note for note in created if note.get("cw") != CW]
    assert not missing, f"CW が引き継がれていないノートがある: {missing!r}"


async def test_speedtest_notes_stay_without_cw_when_command_has_none(
    handler, msk, fast_speedtest
):
    command = fakes.note(
        nid="admin-plain-command",
        user_id="admin-id",
        text="@bot 回線速度を計測して",
    )

    await handler._handle_speedtest(command)

    created = msk.created_notes()
    assert created
    assert all("cw" not in note for note in created), f"余計な CW が付いている: {created!r}"
