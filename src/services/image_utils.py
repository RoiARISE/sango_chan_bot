import asyncio
import base64
import io
import ipaddress
import logging
import socket

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
MAX_IMAGES_COUNT = 3
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_TIMEOUT_SECONDS = 20.0
# 全ユーザーで共有。待機時間も取得全体のタイムアウトに含める。
_image_slots = asyncio.Semaphore(3)
_ALLOWED_FORMATS = ("JPEG", "PNG", "GIF", "WEBP")


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    # IPv4を埋め込むトンネルやスコープ付きIPv6も許可しない。
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and "%" not in value
        and not (isinstance(address, ipaddress.IPv6Address) and (
            address.ipv4_mapped or address.sixtofour or address.teredo
        ))
    )


async def _pinned_url(url: str) -> tuple[httpx.URL, str]:
    original = httpx.URL(url)
    if (original.scheme != "https" or not original.host or original.userinfo
            or original.port not in (None, 443)):
        raise ValueError("HTTPS media URL on port 443 required")
    host = original.host
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        records = await asyncio.get_running_loop().getaddrinfo(
            host, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
        addresses = [record[4][0] for record in records]
    if not addresses or not all(_public_address(addr) for addr in addresses):
        raise ValueError("Non-public media destination")
    # HTTPXは検証済みIPへ接続する。再名前解決させず、TLS検証とHostは元のホストを使う。
    return original.copy_with(host=addresses[0], fragment=None), host


def _normalize_image(content: bytes, max_size: int) -> str:
    # 実際にデコードし、先頭フレームのみ再エンコードすることでメタデータ等も除去する。
    with Image.open(io.BytesIO(content), formats=_ALLOWED_FORMATS) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("Image pixel limit exceeded")
        image.load()
        normalized = image.convert("RGB")
        try:
            output = io.BytesIO()
            normalized.save(output, format="JPEG", quality=85)
            data = output.getvalue()
        finally:
            normalized.close()
    if len(data) > max_size:
        raise ValueError("Normalized image size limit exceeded")
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


async def fetch_image_as_data_url(url: str, max_size_bytes: int = MAX_IMAGE_SIZE_BYTES) -> str | None:
    """公開HTTPSの画像を制限付きで取得し、検証済みのJPEG Data URLを返す。"""
    limit = min(max_size_bytes, MAX_IMAGE_SIZE_BYTES)
    if limit <= 0:
        return None
    try:
        async with asyncio.timeout(IMAGE_TIMEOUT_SECONDS):
            slots = _image_slots
            await slots.acquire()
            normalization = None
            try:
                target, host = await _pinned_url(url)
                # 環境変数のプロキシを介した宛先変更を防止する。リダイレクトは追跡しない。
                async with httpx.AsyncClient(
                    timeout=10.0, follow_redirects=False, trust_env=False
                ) as client:
                    async with client.stream(
                        "GET", target,
                        headers={"Host": host if ":" not in host else f"[{host}]",
                                 "Accept-Encoding": "identity"},
                        extensions={"sni_hostname": host},
                    ) as response:
                        if response.status_code != 200:
                            return None
                        # 圧縮の展開時に巨大な一時バッファが生じることも防ぐ。
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            return None
                        mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
                        if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                            return None
                        length = response.headers.get("content-length")
                        if length is not None and (int(length) < 0 or int(length) > limit):
                            return None
                        content = bytearray()
                        async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                            if len(content) + len(chunk) > limit:
                                return None
                            content.extend(chunk)
                    normalization = asyncio.get_running_loop().run_in_executor(
                        None, _normalize_image, bytes(content), limit
                    )
                    # 呼び出しがタイムアウトしても、デコードが終わるまで枠を保持する。
                    def release_slot(done):
                        slots.release()
                        if not done.cancelled():
                            done.exception()  # タイムアウト後の例外も回収する。
                    normalization.add_done_callback(release_slot)
                    return await asyncio.shield(normalization)
            finally:
                if normalization is None:
                    slots.release()
    except Exception as error:
        # URLのクエリや内部応答、認証情報をログに残さない。
        logger.warning("画像取得を中止しました (%s)", type(error).__name__)
        return None


async def fetch_images_as_data_urls(
    urls: list[str], max_count: int = MAX_IMAGES_COUNT
) -> list[str]:
    target_urls = urls[:max(0, min(max_count, MAX_IMAGES_COUNT))]
    results = await asyncio.gather(*(fetch_image_as_data_url(url) for url in target_urls))
    return [result for result in results if result is not None]
