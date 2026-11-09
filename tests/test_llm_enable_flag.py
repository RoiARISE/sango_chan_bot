"""Regression test: ``LLM_ENABLE=0`` must actually disable the LLM.

``config.LLM_ENABLE`` used to be the raw environment string.  Both the chat
path and the image path tested it for truthiness, so ``"0"`` and ``"false"``
were treated as enabled and the bot kept sending note text and images to the
external endpoint.
"""

from __future__ import annotations

import pytest

import src.config as config
from src.services import openrouter


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " On "])
def test_enabled_values(monkeypatch, raw):
    monkeypatch.setenv("LLM_TEST_FLAG", raw)
    assert config.get_bool_env("LLM_TEST_FLAG") is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "no", "off", "", "   "])
def test_disabled_values(monkeypatch, raw):
    monkeypatch.setenv("LLM_TEST_FLAG", raw)
    assert config.get_bool_env("LLM_TEST_FLAG") is False


def test_missing_variable_uses_default(monkeypatch):
    monkeypatch.delenv("LLM_TEST_FLAG", raising=False)
    assert config.get_bool_env("LLM_TEST_FLAG") is False
    assert config.get_bool_env("LLM_TEST_FLAG", default=True) is True


async def test_disabled_flag_does_not_create_http_client(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("LLM が無効なのに HTTP クライアントを作ろうとした")

    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", False)
    monkeypatch.setattr(openrouter.httpx, "AsyncClient", explode)

    result = await openrouter.chat_with_history(
        [{"role": "user", "content": "こんにちは"}]
    )

    assert result["reason"] == "disabled"


async def test_disabled_flag_skips_profile_analysis(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", False)

    result = await openrouter.analyze_user_interaction([], "", 0, "user")

    assert result == {"description": "", "intimacy_change": 0}
