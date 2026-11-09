"""Regression test: a display name must be neutralized before being posted.

Nicknames go through ``utils.sanitize_nickname`` to stop MFM, mention, hashtag
and link injection. The fallback display name (``user.name``) bypassed that
sanitizer and was interpolated into bot replies. A user could set their display
name to "@victim $[x2 ...] https://evil.example #tag" and the bot would mention
the victim, render MFM and publish a link.
"""

from __future__ import annotations

import fakes

INJECTION_MARKERS = ("@victim", "$[", "://", "#tag", "](")


async def test_display_name_is_sanitized_before_being_posted(handler, msk):
    payload = "@victim $[x2 あ] https://evil.example #tag [click](https://evil.example)"

    malicious_note = fakes.note(
        nid="display-name-note",
        user_id="attacker-id",
        text="@bot フォローして",
        name=payload,
    )

    await handler.handle(malicious_note)

    created = msk.created_notes()
    assert created, f"bot did not reply; calls={msk.calls!r}"

    text = created[0].get("text", "")
    leaked = [marker for marker in INJECTION_MARKERS if marker in text]
    assert not leaked, (
        "display name was copied verbatim into a bot note "
        f"(markers={leaked!r}, text={text!r})"
    )
