import asyncio
import ipaddress
import logging
import socket

import httpx

logger = logging.getLogger(__name__)

MAX_IMAGES_COUNT = 3
URL_VALIDATION_TIMEOUT_SECONDS = 20.0


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


async def validate_image_url(url: str) -> str | None:
    """公開HTTPSの画像URLか検証し、そのままAPIに渡せるURLを返す。"""
    try:
        async with asyncio.timeout(URL_VALIDATION_TIMEOUT_SECONDS):
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
            return str(original.copy_with(fragment=None))
    except Exception as error:
        # URLのクエリや内部応答、認証情報をログに残さない。
        logger.warning("画像URLの検証を中止しました (%s)", type(error).__name__)
        return None


async def validate_image_urls(
    urls: list[str], max_count: int = MAX_IMAGES_COUNT
) -> list[str]:
    target_urls = urls[:max(0, min(max_count, MAX_IMAGES_COUNT))]
    results = await asyncio.gather(*(validate_image_url(url) for url in target_urls))
    return [result for result in results if result is not None]
