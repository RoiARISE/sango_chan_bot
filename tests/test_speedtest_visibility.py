"""Regression test: a private speedtest command must not post a public note.

The admin can request a speedtest from a direct (specified) or followers-only
note. Replies copy the incoming note's visibility, but the intermediate
"計測中だよ……" note used to go out with no reply target and no visibility, so
it became a fully public, detached note. 045bbdd fixed that, and edd32d0
dropped both parameters again while touching an unrelated section.
"""

from __future__ import annotations

from unittest import mock

import fakes
import src.handlers.mention as mention


async def test_private_speedtest_command_never_posts_public_notes(handler, msk):
    async def fast_sleep(_seconds):
        return None

    async def fake_speedtest():
        return "計測かんりょー。下り1.00Mbps、上り1.00Mbps、ping値1.00msだったよ。"

    direct_command = fakes.note(
        nid="admin-direct-command",
        user_id="admin-id",
        text="@bot 回線速度を計測して",
        visibility="specified",
        visibleUserIds=["admin-id"],
    )

    with mock.patch.object(mention.speedtest, "run_speedtest", fake_speedtest), \
         mock.patch.object(mention.asyncio, "sleep", fast_sleep):
        await handler._handle_speedtest(direct_command)

    created = msk.created_notes()
    assert created, "no notes were created"

    leaks = [
        params
        for params in created
        if params.get("visibility") != "specified"
        or not (params.get("reply_id") or params.get("renote_id"))
    ]
    assert not leaks, (
        "a specified-visibility speedtest command created "
        f"{len(leaks)} note(s) without the private visibility or reply target: "
        f"text={leaks[0].get('text', '')!r} params={leaks[0]!r}"
    )
