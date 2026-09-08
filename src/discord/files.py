import base64
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)
IMAGE_MIME = re.compile(r"^image/(png|jpeg|jpg|gif|webp)$", re.IGNORECASE)


def _attachment_mime(attachment: Any) -> str | None:
    content_type = getattr(attachment, "content_type", None)
    if content_type:
        return str(content_type).split(";", 1)[0].strip()
    filename = str(getattr(attachment, "filename", "") or "")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(suffix)


async def fetch_discord_image_data_urls(
    attachments: list[Any] | None,
    *,
    max_images: int = 4,
    max_bytes_per_file: int = 5 * 1024 * 1024,
) -> list[str]:
    if not attachments:
        return []
    out: list[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for attachment in attachments:
            if len(out) >= max_images:
                break
            mimetype = _attachment_mime(attachment)
            if not mimetype or not IMAGE_MIME.match(mimetype):
                continue
            url = getattr(attachment, "url", None) or getattr(attachment, "proxy_url", None)
            if not url:
                continue
            try:
                res = await client.get(str(url))
                if res.status_code >= 400:
                    logger.warning("discord image download failed status=%s", res.status_code)
                    continue
                data = res.content
                if len(data) > max_bytes_per_file:
                    logger.warning("discord image too large; skipping bytes=%s", len(data))
                    continue
                encoded = base64.b64encode(data).decode("ascii")
                out.append(f"data:{mimetype};base64,{encoded}")
            except Exception:
                logger.warning("discord image fetch error", exc_info=True)
    return out
