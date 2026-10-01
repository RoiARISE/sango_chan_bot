import asyncio
import base64
import logging

import httpx

logger = logging.getLogger(__name__)

# 許容する最大画像サイズ (10MB)
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
# 同時に処理する最大画像枚数
MAX_IMAGES_COUNT = 3


async def fetch_image_as_data_url(url: str, max_size_bytes: int = MAX_IMAGE_SIZE_BYTES) -> str | None:
    """
    指定されたURLから画像をダウンロードし、Base64 Data URL形式に変換する。
    例: "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("画像のダウンロードに失敗しました: %s (status=%d)", url, resp.status_code)
                return None

            content = resp.content
            if len(content) > max_size_bytes:
                logger.warning(
                    "画像サイズが上限を超えています (%d bytes > %d bytes): %s",
                    len(content),
                    max_size_bytes,
                    url,
                )
                return None

            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            # MIMEタイプが不明またはimage/以外の場合はimage/jpegをデフォルトとする
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"

            b64_str = base64.b64encode(content).decode("utf-8")
            return f"data:{content_type};base64,{b64_str}"
    except Exception as e:
        logger.error("画像取得・変換エラー (%s): %s", url, e, exc_info=True)
        return None


async def fetch_images_as_data_urls(
    urls: list[str], max_count: int = MAX_IMAGES_COUNT
) -> list[str]:
    """
    複数の画像URLを並行してダウンロードし、Base64 Data URLのリストを返す。
    上限枚数 (max_count) を超える分は切り捨てる。
    """
    target_urls = urls[:max_count]
    if not target_urls:
        return []

    tasks = [fetch_image_as_data_url(u) for u in target_urls]
    results = await asyncio.gather(*tasks)

    # None（失敗したもの）を除外
    data_urls = [r for r in results if r is not None]
    return data_urls
