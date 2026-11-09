"""Regression test: the streaming access token must not reach the log.

``setup_logging`` raises the root logger to DEBUG. ``websockets`` logs the
``GET /streaming?i=<token>`` request line at DEBUG, so the bot's full API token
was written to stdout. The application log level stays DEBUG; only the
websockets library is capped at INFO.
"""

from __future__ import annotations

import logging

from src.logger import setup_logging


def test_websockets_logger_never_emits_debug_request_lines():
    root = logging.getLogger()
    websockets = logging.getLogger("websockets")
    old_root_level = root.level
    old_handlers = root.handlers[:]
    old_websockets_level = websockets.level
    try:
        setup_logging()
        assert root.level == logging.DEBUG
        assert logging.getLogger("src.bot").getEffectiveLevel() == logging.DEBUG
        assert websockets.getEffectiveLevel() >= logging.INFO
    finally:
        root.setLevel(old_root_level)
        root.handlers[:] = old_handlers
        websockets.setLevel(old_websockets_level)
