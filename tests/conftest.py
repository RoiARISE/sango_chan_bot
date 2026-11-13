"""pytest setup for the bot's regression tests.

Puts the repository root on ``sys.path``, fills in the environment variables
``src.config`` needs at import time, and stubs third-party packages that are not
installed. The real package is used whenever it can be imported.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

for path in (str(ROOT), str(TESTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

# src/config.py raises when these are missing. The values never reach the network.
ENV_DEFAULTS = {
    "TOKEN": "test-token",
    "INSTANCE": "test.example.invalid",
    "ADMIN_ID": "admin-id",
    "LLM_ENABLE": "1",
    "LLM_ENDPOINT": "https://llm.test.invalid/api/v1",
    "LLM_API_KEY": "test-key",
    "LLM_MODEL": "test/model",
    "LLM_TIMEOUT": "1",
}
for key, value in ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)

ADMIN_ID = os.environ["ADMIN_ID"]


def _module(name: str) -> types.ModuleType:
    """Import ``name``, falling back to an empty stub when it is absent."""
    try:
        return importlib.import_module(name)
    except ImportError:
        module = sys.modules.get(name) or types.ModuleType(name)
        sys.modules[name] = module
        return module


def _install_stubs() -> None:
    dotenv = _module("dotenv")
    if not hasattr(dotenv, "load_dotenv"):
        dotenv.load_dotenv = lambda *args, **kwargs: None  # type: ignore[attr-defined]

    httpx = _module("httpx")
    if not hasattr(httpx, "AsyncClient"):

        class RequestError(Exception):
            pass

        class TimeoutException(RequestError):
            pass

        class AsyncClient:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                raise RequestError("network disabled in tests")

            async def get(self, *args, **kwargs):
                raise RequestError("network disabled in tests")

        httpx.AsyncClient = AsyncClient  # type: ignore[attr-defined]
        httpx.RequestError = RequestError  # type: ignore[attr-defined]
        httpx.TimeoutException = TimeoutException  # type: ignore[attr-defined]

    misskey = _module("misskey")
    if not hasattr(misskey, "Misskey"):

        class Misskey:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        misskey.Misskey = Misskey  # type: ignore[attr-defined]

    exceptions = _module("misskey.exceptions")
    if not hasattr(exceptions, "MisskeyAPIException"):

        class MisskeyAPIException(Exception):
            def __init__(self, response_dict):
                super().__init__(str(response_dict))
                error = response_dict.get("error", {}) if isinstance(response_dict, dict) else {}
                self.code = error.get("code")
                self.id = error.get("id")
                self.message = error.get("message", str(response_dict))

        exceptions.MisskeyAPIException = MisskeyAPIException  # type: ignore[attr-defined]
        misskey.exceptions = exceptions  # type: ignore[attr-defined]

    speedtest = _module("speedtest")
    if not hasattr(speedtest, "Speedtest"):

        class Speedtest:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("speedtest disabled in tests")

        speedtest.Speedtest = Speedtest  # type: ignore[attr-defined]


_install_stubs()

from fakes import FakeMisskey  # noqa: E402
from src.handlers.mention import MentionHandler  # noqa: E402
from src.stores.user_store import UserStore  # noqa: E402


@pytest.fixture
def msk() -> FakeMisskey:
    return FakeMisskey()


@pytest.fixture
def store(msk: FakeMisskey, tmp_path) -> UserStore:
    store = UserStore(str(tmp_path / "user_data.sqlite3"), msk, msk.my_id)
    store.load()
    return store


@pytest.fixture
def handler(msk: FakeMisskey, store: UserStore) -> MentionHandler:
    return MentionHandler(msk, store, ADMIN_ID)
