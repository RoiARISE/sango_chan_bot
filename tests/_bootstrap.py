"""Import bootstrap for the note-response regression tests.

Only the modules needed by the note-response code paths are loaded. Third-party
dependencies are stubbed so the tests run with the standard library alone:

    python3 tests/test_todo_stop_idor.py
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

_here = Path(__file__).resolve()
_default_root = _here.parents[1]
ROOT = Path(os.environ.get("SANGOU_REPO_ROOT", _default_root)).resolve()
if (ROOT / "src").is_dir() is False:
    raise RuntimeError(f"repository root not found: {ROOT}")
sys.path.insert(0, str(ROOT))

# config.py raises if these are missing. Values are never used to call out.
for key, value in {
    "TOKEN": "test-token",
    "INSTANCE": "test.example.invalid",
    "ADMIN_ID": "admin-id",
    "LLM_ENABLE": "1",
    "LLM_ENDPOINT": "https://llm.test.invalid/api/v1",
    "LLM_API_KEY": "test-key",
    "LLM_MODEL": "test/model",
    "LLM_TIMEOUT": "1",
}.items():
    os.environ.setdefault(key, value)


def _stub(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


# python-dotenv
dotenv = _stub("dotenv")
if not hasattr(dotenv, "load_dotenv"):
    dotenv.load_dotenv = lambda *args, **kwargs: None  # type: ignore[attr-defined]

# httpx (only imported, never used by the tests)
httpx = _stub("httpx")
if not hasattr(httpx, "AsyncClient"):

    class _TransportError(Exception):
        pass

    class _TimeoutException(_TransportError):
        pass

    class _RequestError(_TransportError):
        pass

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):  # pragma: no cover - never called
            raise _RequestError("network disabled in tests")

        async def get(self, *args, **kwargs):  # pragma: no cover - never called
            raise _RequestError("network disabled in tests")

    httpx.AsyncClient = _AsyncClient  # type: ignore[attr-defined]
    httpx.TimeoutException = _TimeoutException  # type: ignore[attr-defined]
    httpx.RequestError = _RequestError  # type: ignore[attr-defined]

# Misskey.py (client only)
misskey = _stub("misskey")
if not hasattr(misskey, "Misskey"):

    class Misskey:  # pragma: no cover - replaced by FakeMisskey
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    misskey.Misskey = Misskey  # type: ignore[attr-defined]

exceptions = _stub("misskey.exceptions")
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

# speedtest-cli
speedtest = _stub("speedtest")
if not hasattr(speedtest, "Speedtest"):

    class Speedtest:  # pragma: no cover - patched per test
        def __init__(self, *args, **kwargs):
            raise RuntimeError("speedtest disabled in tests")

    speedtest.Speedtest = Speedtest  # type: ignore[attr-defined]
