import asyncio
import socket
import unittest
from unittest.mock import AsyncMock, patch

from src.services import image_utils as images


class ImageUrlValidationTests(unittest.IsolatedAsyncioTestCase):
    async def validate(self, url):
        return await images.validate_image_url(url)

    async def test_public_https_url_is_passed_through(self):
        self.assertEqual(
            await self.validate("https://8.8.8.8/image?token=dummy#fragment"),
            "https://8.8.8.8/image?token=dummy",
        )

    async def test_dns_is_resolved_and_public_hosts_are_accepted(self):
        resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                           ("8.8.8.8", 443))])
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", resolver):
            self.assertEqual(
                await self.validate("https://media.example/image"),
                "https://media.example/image",
            )
        resolver.assert_awaited_once()

    async def test_unsafe_urls_are_rejected(self):
        for url in ["http://8.8.8.8/a", "file:///etc/passwd", "https://127.0.0.1/a",
                    "https://10.0.0.1/a", "https://169.254.169.254/a", "https://100.64.0.1/a",
                    "https://[::1]/a", "https://[fc00::1]/a", "https://[fe80::1%25eth0]/a",
                    "https://[::ffff:8.8.8.8]/a", "https://224.0.0.1/a",
                    "https://user:pass@8.8.8.8/a", "https://8.8.8.8:8443/a",
                    "not a url"]:
            with self.subTest(url=url):
                self.assertIsNone(await self.validate(url))

    async def test_mixed_public_and_private_dns_is_rejected(self):
        resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                                           for ip in ["8.8.8.8", "127.0.0.1"]])
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", resolver):
            self.assertIsNone(await self.validate("https://media.example/a"))

    async def test_total_timeout_includes_dns(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        with patch.object(images, "URL_VALIDATION_TIMEOUT_SECONDS", 0.01):
            with patch.object(asyncio.get_running_loop(), "getaddrinfo", side_effect=slow):
                self.assertIsNone(await self.validate("https://media.example/a"))

    async def test_max_count_cannot_increase_hard_limit(self):
        validated = AsyncMock(return_value="https://8.8.8.8/a")
        with patch.object(images, "validate_image_url", validated):
            self.assertEqual(
                await images.validate_image_urls(["a"] * 10, 100),
                ["https://8.8.8.8/a"] * 3,
            )
            self.assertEqual(validated.await_count, 3)
            self.assertEqual(await images.validate_image_urls(["a"], -1), [])

    async def test_invalid_urls_are_dropped_from_the_list(self):
        async def validate(url):
            return None if "bad" in url else url
        with patch.object(images, "validate_image_url", side_effect=validate):
            self.assertEqual(
                await images.validate_image_urls(["https://a.example", "https://bad.example",
                                                  "https://b.example"]),
                ["https://a.example", "https://b.example"],
            )

    async def test_failures_do_not_log_url_secrets(self):
        with self.assertLogs(images.logger, level="WARNING") as logs:
            self.assertIsNone(await self.validate("https://user:SECRET@127.0.0.1/a?token=SECRET"))
        self.assertNotIn("SECRET", "".join(logs.output))


if __name__ == "__main__":
    unittest.main()
