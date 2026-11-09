"""Unit tests for ``src.services.speedtest``.

The real ``speedtest-cli`` talks to remote servers. The tests replace its
``Speedtest`` class and check only the formatting and error path.
"""

from __future__ import annotations

from unittest import mock

import src.services.speedtest as speedtest_service


class FakeResult:
    ping = 12.345


class FakeSpeedtest:
    def __init__(self, secure=None):
        self.secure = secure
        self.results = FakeResult()
        self.calls = []

    def get_best_server(self):
        self.calls.append("get_best_server")

    def download(self):
        self.calls.append("download")
        return 12_345_678

    def upload(self):
        self.calls.append("upload")
        return 6_789_012


async def test_run_speedtest_formats_mbps_and_ping():
    fake = FakeSpeedtest()

    with mock.patch.object(speedtest_service.speedtest_lib, "Speedtest", return_value=fake) as factory:
        result = await speedtest_service.run_speedtest()

    factory.assert_called_once_with(secure=True)
    assert fake.calls == ["get_best_server", "download", "upload"]
    assert "下り12.35Mbps" in result
    assert "上り6.79Mbps" in result
    assert "ping値12.35ms" in result


async def test_run_speedtest_reports_errors():
    with mock.patch.object(
        speedtest_service.speedtest_lib,
        "Speedtest",
        side_effect=RuntimeError("no server"),
    ):
        result = await speedtest_service.run_speedtest()

    assert "計測中にエラーが起きちゃったみたい" in result
    assert "no server" in result
