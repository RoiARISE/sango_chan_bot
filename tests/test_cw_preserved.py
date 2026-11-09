"""Regression test: a reply must keep the content warning of the parent note.

``_get_reply_kwargs`` copies the visibility of the incoming note but never its
``cw``. Misskey does not add a content warning to a reply on its own, so a bot
reply to a CW note lands on the timeline without the warning that the author
used to hide spoilers or sensitive topics.
"""

from __future__ import annotations

import fakes


async def test_reply_keeps_the_content_warning(handler, msk):
    cw_note = fakes.note(
        nid="cw-note",
        user_id="user-1",
        text="@bot この話どう思う？",
        cw="ネタバレを含みます",
    )

    await handler._send_reply(cw_note, text="わたしからは伏せておくね")

    created = msk.created_notes()
    assert created, "bot did not reply"
    assert created[0].get("cw") == "ネタバレを含みます", (
        "reply dropped the parent note's content warning: "
        f"params={created[0]!r}"
    )
    assert created[0].get("visibility") == "public"


async def test_reply_without_cw_stays_without_cw(handler, msk):
    plain_note = fakes.note(nid="plain-note", user_id="user-1", text="@bot やあ")

    await handler._send_reply(plain_note, text="やあ")

    created = msk.created_notes()
    assert created, "bot did not reply"
    assert "cw" not in created[0], f"unexpected cw: params={created[0]!r}"
