"""Regression test: a display name must be neutralized before being posted.

Nicknames go through ``utils.sanitize_nickname`` to stop MFM, mention, hashtag
and link injection. The fallback display name (``user.name``) bypassed that
sanitizer and was interpolated into bot replies. A user could set their display
name to "@victim $[x2 ...] https://evil.example #tag" and the bot would mention
the victim, render MFM and publish a link.
"""

from __future__ import annotations

import asyncio

import _bootstrap  # noqa: F401
import _fakes as fakes


INJECTION_MARKERS = ("@victim", "$[", "://", "#tag", "](")


async def main() -> None:
    payload = "@victim $[x2 あ] https://evil.example #tag [click](https://evil.example)"
    msk = fakes.FakeMisskey(relation={"isFollowing": True, "isFollowed": True})
    handler, _store, _tmp = fakes.make_handler(msk)

    malicious_note = fakes.note(
        nid="display-name-note",
        user_id="attacker-id",
        text="@bot フォローして",
        name=payload,
    )

    await handler.handle(malicious_note)

    created = msk.created_notes()
    if not created:
        raise SystemExit(f"HARNESS: bot did not reply; calls={msk.calls!r}")

    text = created[0].get("text", "")
    leaked = [marker for marker in INJECTION_MARKERS if marker in text]

    if leaked:
        fakes.finish_vulnerable(
            "display name was copied verbatim into a bot note "
            f"(markers={leaked!r}, text={text!r})"
        )
    fakes.finish_ok("display names are neutralized before being placed in notes")


if __name__ == "__main__":
    asyncio.run(main())
