"""Unit tests for ``src.services.openrouter``.

HTTP is replaced with a small in-process client so request payloads, headers and
every error branch of ``chat_with_history`` / ``analyze_user_interaction`` can be
checked without network access.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

import src.services.openrouter as openrouter


class FakeResponse:
    def __init__(self, status=200, body=None, text="", json_error=False):
        self.status_code = status
        self._body = body
        self.text = text if text else json.dumps(body, ensure_ascii=False)
        self._json_error = json_error

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._body


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, **kwargs):
        self.request = kwargs
        if self.error is not None:
            raise self.error
        return self.response


def install_client(response=None, error=None):
    FakeClient.instances.clear()

    def factory(*args, **kwargs):
        return FakeClient(response=response, error=error)

    return mock.patch.object(openrouter.httpx, "AsyncClient", side_effect=factory)


def choice(content):
    return {"choices": [{"message": {"content": content}}]}


async def test_chat_returns_disabled_message_when_llm_is_off(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", False)

    result = await openrouter.chat_with_history([{"role": "user", "content": "やあ"}])

    assert result["reason"] == "disabled"
    assert result["reply"] == "その機能は使えないんだ。ごめんね。"


async def test_chat_sends_system_prompt_history_and_auth_header(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)
    monkeypatch.setattr(openrouter.config, "LLM_API_KEY", "test-key")
    body = choice(json.dumps({"action": "reply", "reply": "やあ", "reaction": "❤️", "reason": "ok"}))
    response = FakeResponse(body=body)

    with install_client(response=response):
        result = await openrouter.chat_with_history(
            [{"role": "user", "content": "こんにちは"}],
            user_profile="チョコ好き",
            intimacy=12,
            convo_context="1ターン目です",
        )

    assert result == {"action": "reply", "reaction": "❤️", "reply": "やあ", "reason": "ok"}
    request = FakeClient.instances[0].request
    assert request["url"] == "https://llm.test.invalid/api/v1/chat/completions"
    assert request["headers"] == {"Authorization": "Bearer test-key"}
    assert request["json"]["model"] == "test/model"
    assert request["timeout"] == 1.0

    system = request["json"]["messages"][0]
    assert system["role"] == "system"
    assert "チョコ好き" in system["content"]
    assert "12" in system["content"]
    assert "1ターン目です" in system["content"]
    assert request["json"]["messages"][-1] == {"role": "user", "content": "こんにちは"}


async def test_chat_turns_the_last_user_message_into_multimodal(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)
    response = FakeResponse(body=choice('{"action":"reply","reply":"かわいい"}'))
    history = [{"role": "user", "content": "みて"}]

    with install_client(response=response):
        await openrouter.chat_with_history(
            history, image_data_urls=["data:image/png;base64,AAAA"]
        )

    request = FakeClient.instances[0].request
    content = request["json"]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "みて"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64,AAAA"
    # The caller's history must not be mutated.
    assert history == [{"role": "user", "content": "みて"}]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (openrouter.httpx.TimeoutException("slow"), "timeout"),
        (openrouter.httpx.RequestError("down"), "request_error"),
        (ValueError("weird"), "unexpected_error"),
    ],
)
async def test_chat_maps_transport_errors(monkeypatch, error, reason):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(error=error):
        result = await openrouter.chat_with_history([{"role": "user", "content": "やあ"}])

    assert result["reason"] == reason
    assert "通信中にエラー" in result["reply"]


async def test_chat_maps_non_success_status(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(response=FakeResponse(status=503, body={})):
        result = await openrouter.chat_with_history([{"role": "user", "content": "やあ"}])

    assert result["reason"] == "status_503"


async def test_chat_rejects_unparsable_json(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(response=FakeResponse(body={}, json_error=True)):
        result = await openrouter.chat_with_history([{"role": "user", "content": "やあ"}])

    assert result["reason"] == "raw_json_parse_error"


async def test_chat_rejects_error_body(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(response=FakeResponse(body={"error": {"message": "quota"}})):
        result = await openrouter.chat_with_history([{"role": "user", "content": "やあ"}])

    assert result["reason"] == "api_error_body"


async def test_chat_rejects_missing_choices(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(response=FakeResponse(body={"choices": []})):
        result = await openrouter.chat_with_history([{"role": "user", "content": "やあ"}])

    assert result["reason"] == "no_choices"


async def test_chat_rejects_empty_content(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(response=FakeResponse(body=choice("   "))):
        result = await openrouter.chat_with_history([{"role": "user", "content": "やあ"}])

    assert result["reason"] == "empty_content"
    assert result["reaction"] == "❓"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"action":"reply","reply":"やあ"}', ("reply", "やあ")),
        ('```json\n{"action":"react","reaction":"👍"}\n```', ("react", "")),
        ('前置き {"action":"none","reply":"x"} 後置き', ("none", "x")),
        ("not json at all", ("reply", "not json at all")),
    ],
)
def test_parse_llm_response(content, expected):
    parsed = openrouter._parse_llm_response(content)
    assert (parsed["action"], parsed["reply"]) == expected


def test_parse_llm_response_marks_fallback():
    parsed = openrouter._parse_llm_response("ただの文章")
    assert parsed["reason"] == "json_parse_fallback"
    assert parsed["reaction"] == "❤️"


def test_normalize_response_dict_sanitizes_values():
    assert openrouter._normalize_response_dict({"action": "REPLY", "reply": " やあ "}) == {
        "action": "reply",
        "reaction": "❤️",
        "reply": "やあ",
        "reason": "",
    }

    # Unknown actions fall back to reply; a reply without text becomes react.
    assert openrouter._normalize_response_dict({"action": "dance", "reply": "x"})["action"] == "reply"
    assert openrouter._normalize_response_dict({"action": "reply", "reply": ""})["action"] == "react"
    assert openrouter._normalize_response_dict({"action": "reply", "reply": None})["action"] == "react"


def test_auth_headers_use_api_key_when_configured(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_API_KEY", "secret")

    assert openrouter._get_auth_headers() == {"Authorization": "Bearer secret"}


def test_auth_headers_fall_back_when_google_auth_fails(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_API_KEY", "")
    monkeypatch.setattr(openrouter, "_gcp_credentials", None)

    with mock.patch("google.auth.default", side_effect=RuntimeError("no adc")):
        headers = openrouter._get_auth_headers()

    assert headers["Authorization"].startswith("Bearer ")


def test_auth_headers_use_google_credentials(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_API_KEY", "")
    monkeypatch.setattr(openrouter, "_gcp_credentials", None)
    credentials = mock.Mock(valid=True, token="google-token")

    with mock.patch("google.auth.default", return_value=(credentials, "project")):
        headers = openrouter._get_auth_headers()

    assert headers == {"Authorization": "Bearer google-token"}


async def test_analyze_returns_defaults_when_disabled(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", False)

    result = await openrouter.analyze_user_interaction([], "", 0, "みー")

    assert result == {"description": "", "intimacy_change": 0}


async def test_analyze_parses_description_and_intimacy(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)
    content = '```json\n{"description":" チョコ好き ","intimacy_change":2}\n```'

    with install_client(response=FakeResponse(body=choice(content))):
        result = await openrouter.analyze_user_interaction(
            [{"role": "user", "content": "こんにちは"}], "既存", 3, "みー"
        )

    assert result == {"description": "チョコ好き", "intimacy_change": 2}
    prompt = FakeClient.instances[0].request["json"]["messages"][0]["content"]
    assert "ユーザー: こんにちは" in prompt
    assert "既存" in prompt
    assert "3" in prompt


async def test_analyze_returns_defaults_on_bad_response(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(response=FakeResponse(status=500, body={})):
        assert await openrouter.analyze_user_interaction([], "", 0, "みー") == {
            "description": "",
            "intimacy_change": 0,
        }

    with install_client(response=FakeResponse(body=choice("not json"))):
        assert await openrouter.analyze_user_interaction([], "", 0, "みー") == {
            "description": "",
            "intimacy_change": 0,
        }


async def test_analyze_returns_defaults_on_transport_error(monkeypatch):
    monkeypatch.setattr(openrouter.config, "LLM_ENABLE", True)

    with install_client(error=RuntimeError("down")):
        result = await openrouter.analyze_user_interaction([], "", 0, "みー")

    assert result == {"description": "", "intimacy_change": 0}
