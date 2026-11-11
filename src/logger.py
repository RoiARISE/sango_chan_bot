from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

import structlog
from dotenv import load_dotenv

LOG_FORMAT_ENV = "LOG_FORMAT"
_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
_HANDLER_MARKER = "_sango_chan_log_handler"

# LogRecord が標準で持つ属性。これ以外の属性は extra= で渡された
# 構造化ログ用のフィールドとして出力する。
_RESERVED_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


def _add_timestamp(logger, method_name, event_dict):
    """ローカルタイムゾーン付きの ISO 8601 タイムスタンプを付与する。

    標準 logging のレコードは、ハンドラーでの処理時刻ではなく
    レコード生成時刻 (record.created) を使う。
    """
    record = event_dict.get("_record")
    if record is None:
        now = datetime.now().astimezone()
    else:
        now = datetime.fromtimestamp(record.created).astimezone()
    event_dict["timestamp"] = now.isoformat(timespec="milliseconds")
    return event_dict


def _rename_event_to_message(logger, method_name, event_dict):
    """structlog 標準の event キーを message に揃える。

    出力の先頭に message が来るよう、新しい dict を組み立てる。
    """
    if "event" not in event_dict:
        return event_dict
    event_dict.pop("message", None)
    return {"message": event_dict.pop("event"), **event_dict}


def _merge_record_extras(logger, method_name, event_dict):
    """標準 logging の extra=... を構造化フィールドとして取り込む。

    ProcessorFormatter は標準 logging の extra を event_dict に含めないため、
    元の LogRecord から追加フィールドをコピーする。
    """
    record = event_dict.get("_record")
    if record is not None:
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                event_dict.setdefault(key, value)
    return event_dict


def _format_text_timestamp(timestamp: str) -> str:
    """ISO 8601 のタイムスタンプを従来のテキスト形式に変換する。"""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return timestamp
    return f"{parsed:%Y-%m-%d %H:%M:%S},{parsed.microsecond // 1000:03d}"


class _TextRenderer:
    """従来のテキスト形式に近い1行ログを組み立てる。"""

    def __call__(self, logger, method_name, event_dict):
        timestamp = _format_text_timestamp(event_dict.pop("timestamp", ""))
        level = str(event_dict.pop("level", method_name)).upper()
        logger_name = event_dict.pop("logger", getattr(logger, "name", ""))
        event = event_dict.pop("message", "")
        exception = event_dict.pop("exception", None)
        stack = event_dict.pop("stack", None)

        extras = " ".join(
            f"{key}={value}" for key, value in event_dict.items()
        )
        line = f"{timestamp} [{level:<5}] {logger_name}: {event}"
        if extras:
            line = f"{line} {extras}"
        if stack:
            line = f"{line}\n{stack}"
        if exception:
            line = f"{line}\n{exception}"
        return line


def setup_logging(level: int = logging.DEBUG, log_format: str | None = None) -> None:
    """ルートロガーと structlog を設定する。

    log_format を省略した場合は .env と環境変数 LOG_FORMAT を使う。
    "text" (デフォルト) は従来の人間向け形式、"json" は構造化ログになる。
    """
    # setup_logging() を単体で呼ぶ entrypoint でも .env の設定が効くようにする。
    # 既存の環境変数が優先される (override=False)。
    load_dotenv(dotenv_path=_ENV_PATH)

    selected = (
        log_format
        if log_format is not None
        else os.getenv(LOG_FORMAT_ENV, "text")
    )
    selected = (selected or "text").strip().lower()

    if selected in ("text", "plain"):
        renderer = _TextRenderer()
    elif selected == "json":
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        raise ValueError(
            f"Unsupported {LOG_FORMAT_ENV}={selected!r}: expected 'text' or 'json'"
        )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        _add_timestamp,
        structlog.processors.StackInfoRenderer(),
    ]
    # structlog.get_logger() で取得したロガーも標準 logging を経由させ、
    # ハンドラー側の ProcessorFormatter で描画する。
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            _merge_record_extras,
            _rename_event_to_message,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root = logging.getLogger()
    # setup_logging() が複数回呼ばれてもログが二重に出ないよう、
    # この関数が追加したハンドラーだけを差し替える。
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    setattr(handler, _HANDLER_MARKER, True)
    root.setLevel(level)
    root.addHandler(handler)
    # websockets writes the streaming request line at DEBUG, including the
    # access token in the query string. Keep our own DEBUG logs, but never
    # let that URL reach the log.
    logging.getLogger("websockets").setLevel(logging.INFO)
