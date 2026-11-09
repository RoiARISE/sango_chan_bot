import asyncio
import base64
import io
import socket
import threading
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

from src.services import image_utils as images


def png():
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    return output.getvalue()


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self):
        self.closed = True


class ImageSecurityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client_class = httpx.AsyncClient
        self.requests = []
        self.response = lambda: httpx.Response(200, headers={"content-type": "image/png"},
                                               stream=Stream([png()]))
        self.slots = patch.object(images, "_image_slots", asyncio.Semaphore(3))
        self.slots.start()
        self.addCleanup(self.slots.stop)

    async def fetch(self, url="https://8.8.8.8/image", **kwargs):
        def handler(request):
            self.requests.append(request)
            return self.response()

        def client(**options):
            self.assertFalse(options["follow_redirects"])
            self.assertFalse(options["trust_env"])
            return self.client_class(transport=httpx.MockTransport(handler), **options)

        with patch.object(images.httpx, "AsyncClient", side_effect=client):
            return await images.fetch_image_as_data_url(url, **kwargs)

    async def test_image_decoded_and_normalized(self):
        result = await self.fetch()
        self.assertTrue(result.startswith("data:image/jpeg;base64,"))
        with Image.open(io.BytesIO(base64.b64decode(result.split(",", 1)[1]))) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (2, 2))

    async def test_unsafe_urls_never_connect(self):
        for url in ["http://8.8.8.8/a", "file:///etc/passwd", "https://127.0.0.1/a",
                    "https://10.0.0.1/a", "https://169.254.169.254/a", "https://100.64.0.1/a",
                    "https://[::1]/a", "https://[fc00::1]/a", "https://[fe80::1%25eth0]/a",
                    "https://[::ffff:8.8.8.8]/a", "https://224.0.0.1/a",
                    "https://user:pass@8.8.8.8/a", "https://8.8.8.8:8443/a"]:
            with self.subTest(url=url):
                self.assertIsNone(await self.fetch(url))
        self.assertEqual(self.requests, [])

    async def test_dns_is_pinned_and_tls_hostname_preserved(self):
        resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                           ("8.8.8.8", 443))])
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", resolver):
            self.assertIsNotNone(await self.fetch("https://media.example/image?token=dummy"))
        resolver.assert_awaited_once()
        request = self.requests[0]
        self.assertEqual(request.url.host, "8.8.8.8")
        self.assertEqual(request.headers["host"], "media.example")
        self.assertEqual(request.extensions["sni_hostname"], "media.example")

    async def test_mixed_public_and_private_dns_is_rejected(self):
        resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                                           for ip in ["8.8.8.8", "127.0.0.1"]])
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", resolver):
            self.assertIsNone(await self.fetch("https://media.example/a"))
        self.assertFalse(self.requests)

    async def test_redirect_is_not_followed(self):
        self.response = lambda: httpx.Response(302, headers={"location": "https://127.0.0.1/secret"})
        self.assertIsNone(await self.fetch())
        self.assertEqual(len(self.requests), 1)

    async def test_non_images_and_compressed_responses_rejected_before_read(self):
        for headers in [{"content-type": "text/plain"}, {}, {"content-type": "image/svg+xml"},
                        {"content-type": "image/png", "content-encoding": "gzip"},
                        {"content-type": "image/png", "content-length": "999999999"},
                        {"content-type": "image/png", "content-length": "invalid"}]:
            stream = Stream([png()])
            self.response = lambda: httpx.Response(200, headers=headers, stream=stream)
            self.assertIsNone(await self.fetch())
            self.assertEqual(stream.read_count, 0)
            self.assertTrue(stream.closed)

    async def test_spoofed_image_mime_is_rejected(self):
        self.response = lambda: httpx.Response(200, headers={"content-type": "image/png"},
                                               stream=Stream([b"internal secret, not an image"]))
        self.assertIsNone(await self.fetch())

    async def test_stream_stops_at_limit_without_content_length(self):
        stream = Stream([b"x" * 65536] * 10)
        self.response = lambda: httpx.Response(200, headers={"content-type": "image/png"}, stream=stream)
        self.assertIsNone(await self.fetch(max_size_bytes=65536))
        self.assertEqual(stream.read_count, 2)
        self.assertTrue(stream.closed)

    async def test_pixel_limit(self):
        with patch.object(images, "MAX_IMAGE_PIXELS", 3):
            self.assertIsNone(await self.fetch())

    async def test_output_limit(self):
        self.assertLess(len(png()), 200)
        self.assertIsNone(await self.fetch(max_size_bytes=200))

    async def test_total_timeout_includes_dns_and_semaphore_wait(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        with patch.object(images, "IMAGE_TIMEOUT_SECONDS", 0.01):
            with patch.object(asyncio.get_running_loop(), "getaddrinfo", side_effect=slow):
                self.assertIsNone(await self.fetch("https://media.example/a"))
            with patch.object(images, "_image_slots", asyncio.Semaphore(0)):
                self.assertIsNone(await self.fetch())
        self.assertFalse(self.requests)

    async def test_timeout_closes_slow_stream(self):
        class SlowStream(Stream):
            async def __aiter__(self):
                await asyncio.sleep(1)
                yield png()
        stream = SlowStream([])
        self.response = lambda: httpx.Response(200, headers={"content-type": "image/png"}, stream=stream)
        with patch.object(images, "IMAGE_TIMEOUT_SECONDS", 0.01):
            self.assertIsNone(await self.fetch())
        self.assertTrue(stream.closed)

    async def test_concurrent_downloads_are_limited(self):
        entered = 0
        peak = 0
        class SlowStream(Stream):
            async def __aiter__(self):
                nonlocal entered, peak
                entered += 1
                peak = max(peak, entered)
                try:
                    await asyncio.sleep(0.01)
                    yield png()
                finally:
                    entered -= 1
        def handler(request):
            return httpx.Response(200, headers={"content-type": "image/png"}, stream=SlowStream([]))
        def client(**options):
            return self.client_class(transport=httpx.MockTransport(handler), **options)
        with patch.object(images.httpx, "AsyncClient", side_effect=client):
            results = await asyncio.gather(*(images.fetch_image_as_data_url("https://8.8.8.8/a")
                                            for _ in range(8)))
        self.assertTrue(all(results))
        self.assertEqual(peak, 3)

    async def test_timed_out_decoder_keeps_slot_until_finished(self):
        started = threading.Event()
        finish = threading.Event()
        def normalize(*args):
            started.set()
            finish.wait(2)
            return "ok"
        slots = asyncio.Semaphore(1)
        with patch.object(images, "_image_slots", slots), patch.object(images, "_normalize_image", normalize):
            try:
                with patch.object(images, "IMAGE_TIMEOUT_SECONDS", 0.05):
                    self.assertIsNone(await self.fetch())
                self.assertTrue(started.is_set())
                self.assertTrue(slots.locked())
            finally:
                finish.set()
            # スレッド完了のコールバックが枠を返すまで待つ。
            await asyncio.wait_for(slots.acquire(), timeout=1)
            slots.release()

    async def test_max_count_cannot_increase_hard_limit(self):
        with patch.object(images, "fetch_image_as_data_url", new_callable=AsyncMock, return_value="ok") as fetch:
            self.assertEqual(await images.fetch_images_as_data_urls(["a"] * 10, 100), ["ok"] * 3)
            self.assertEqual(fetch.await_count, 3)
            self.assertEqual(await images.fetch_images_as_data_urls(["a"], -1), [])

    async def test_failures_do_not_log_url_secrets(self):
        with self.assertLogs(images.logger, level="WARNING") as logs:
            self.assertIsNone(await self.fetch("https://user:SECRET@127.0.0.1/a?token=SECRET"))
        self.assertNotIn("SECRET", "".join(logs.output))


if __name__ == "__main__":
    unittest.main()
