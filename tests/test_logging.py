"""Logging regression tests.

The streaming access token must not reach the log: ``setup_logging`` raises the
root logger to DEBUG, while ``websockets`` logs the ``GET /streaming?i=<token>``
request line at DEBUG. The application stays at DEBUG; only the websockets
library is capped at INFO.

The other tests cover the optional structured (JSON) output format and the
structlog integration for both stdlib ``logging`` and structlog loggers.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextlib import contextmanager
from datetime import datetime

import pytest
import structlog

from src.logger import setup_logging


@contextmanager
def _preserve_logging_state():
    """Restore logging/structlog state after a test calls setup_logging."""
    root = logging.getLogger()
    websockets = logging.getLogger("websockets")
    old_root_level = root.level
    old_handlers = root.handlers[:]
    old_websockets_level = websockets.level
    try:
        yield root
    finally:
        root.setLevel(old_root_level)
        root.handlers[:] = old_handlers
        websockets.setLevel(old_websockets_level)
        structlog.reset_defaults()


def _captured_line(capsys, needle: str) -> str:
    lines = capsys.readouterr().out.strip().splitlines()
    return next(line for line in lines if needle in line)


def test_websockets_logger_never_emits_debug_request_lines():
    with _preserve_logging_state() as root:
        setup_logging()
        assert root.level == logging.DEBUG
        assert logging.getLogger("src.bot").getEffectiveLevel() == logging.DEBUG
        assert (
            logging.getLogger("websockets").getEffectiveLevel() >= logging.INFO
        )


def test_setup_logging_defaults_to_text(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    # 開発者の .env に LOG_FORMAT が設定されていても影響を受けないようにする
    monkeypatch.setattr("src.logger._ENV_PATH", str(tmp_path / "missing.env"))
    with _preserve_logging_state():
        setup_logging()
        logging.getLogger("src.test.text").info("テキストログ")

        line = _captured_line(capsys, "テキストログ")

    # 従来どおりのテキスト形式（タイムスタンプ・レベル・ロガー名）を保つ
    assert re.match(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} "
        r"\[INFO \] src\.test\.text: テキストログ$",
        line,
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)


def test_setup_logging_emits_json_lines(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    with _preserve_logging_state():
        setup_logging()
        logging.getLogger("src.test.json").info(
            "テスト %s", "メッセージ", extra={"user_id": "u1"}
        )

        line = _captured_line(capsys, '"src.test.json"')

    payload = json.loads(line)
    assert payload["message"] == "テスト メッセージ"
    assert "event" not in payload
    assert payload["level"] == "info"
    assert payload["logger"] == "src.test.json"
    assert payload["user_id"] == "u1"
    assert "timestamp" in payload
    # ensure_ascii=False なので日本語がエスケープされない
    assert "テスト" in line


def test_json_logging_includes_exception_stacktrace(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    with _preserve_logging_state():
        setup_logging()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logging.getLogger("src.test.json").exception("失敗しました")

        line = _captured_line(capsys, '"src.test.json"')

    payload = json.loads(line)
    assert payload["message"] == "失敗しました"
    assert "Traceback" in payload["exception"]
    assert "RuntimeError: boom" in payload["exception"]


def test_structlog_logger_emits_json(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    with _preserve_logging_state():
        setup_logging()
        structlog.get_logger("src.test.structlog").info(
            "structlogから", user_id="u2"
        )

        line = _captured_line(capsys, '"src.test.structlog"')

    payload = json.loads(line)
    assert payload["message"] == "structlogから"
    assert "event" not in payload
    assert payload["level"] == "info"
    assert payload["logger"] == "src.test.structlog"
    assert payload["user_id"] == "u2"


def test_setup_logging_does_not_duplicate_handlers(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    with _preserve_logging_state():
        setup_logging()
        setup_logging()
        logging.getLogger("src.test.once").info("一度だけ")

        lines = capsys.readouterr().out.strip().splitlines()

    matched = [line for line in lines if '"src.test.once"' in line]
    assert len(matched) == 1


def test_json_timestamp_uses_record_created(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    fixed_created = 1_700_000_000.0

    class FixedCreatedFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.created = fixed_created
            return True

    log_filter = FixedCreatedFilter()
    target = logging.getLogger("src.test.time")
    target.addFilter(log_filter)
    try:
        with _preserve_logging_state():
            setup_logging()
            target.info("記録時刻")
            line = _captured_line(capsys, '"src.test.time"')
    finally:
        target.removeFilter(log_filter)

    payload = json.loads(line)
    expected = (
        datetime.fromtimestamp(fixed_created)
        .astimezone()
        .isoformat(timespec="milliseconds")
    )
    assert payload["timestamp"] == expected


def test_setup_logging_loads_log_format_from_env_file(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text('LOG_FORMAT="json"\n', encoding="utf-8")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.setattr("src.logger._ENV_PATH", str(env_file))

    with _preserve_logging_state():
        setup_logging()
        logging.getLogger("src.test.dotenv").info("env file")
        line = _captured_line(capsys, '"src.test.dotenv"')

    payload = json.loads(line)
    assert payload["message"] == "env file"


def test_setup_logging_rejects_unknown_format():
    with _preserve_logging_state(), pytest.raises(ValueError):
        setup_logging(log_format="xml")
