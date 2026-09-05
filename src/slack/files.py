import logging
import re

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)
IMAGE_MIME = re.compile(r"^image/(png|jpeg|jpg|gif|webp)$", re.IGNORECASE)


async def fetch_slack_image_data_urls(
    files: list[dict] | None,
    *,
    max_images: int = 4,
    max_bytes_per_file: int = 5 * 1024 * 1024,
) -> list[str]:
    if not files:
        return []
    settings = get_settings()
    out: list[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for file in files:
            if len(out) >= max_images:
                break
            mimetype = file.get("mimetype")
            if not mimetype or not IMAGE_MIME.match(mimetype):
                continue
            url = file.get("url_private_download") or file.get("url_private")
            if not url:
                continue
            try:
                res = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                )
                if res.status_code >= 400:
                    logger.warning("slack image download failed status=%s", res.status_code)
                    continue
                data = res.content
                if len(data) > max_bytes_per_file:
                    logger.warning("slack image too large; skipping bytes=%s", len(data))
                    continue
                import base64

                encoded = base64.b64encode(data).decode("ascii")
                out.append(f"data:{mimetype};base64,{encoded}")
            except Exception:
                logger.warning("slack image fetch error", exc_info=True)
    return out
