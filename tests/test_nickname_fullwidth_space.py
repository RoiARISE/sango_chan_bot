"""Regression test: whitespace-only nicknames must count as missing.

``extract_nickname`` used to strip only ASCII spaces, so "@bot 　って呼んで"
(U+3000 ideographic space) produced a one-character nickname. The handler then
rejected it as invalid instead of asking the user to say the name again.
"""

from __future__ import annotations

import pytest

from src import utils


@pytest.mark.parametrize(
    "text",
    [
        "@bot 　って呼んで",
        "@bot 　 　って呼んで",
        "@bot 　と呼んで",
        "@bot \t って呼んで",
    ],
)
def test_whitespace_only_nickname_is_missing(text):
    assert utils.extract_nickname(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@bot さんごって呼んで", "さんご"),
        ("@bot さんご、って呼んで", "さんご"),
        ("さんごって呼んで", "さんご"),
    ],
)
def test_normal_nickname_is_extracted(text, expected):
    assert utils.extract_nickname(text) == expected
