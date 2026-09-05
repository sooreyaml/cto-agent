import httpx

from src.config import get_settings
from src.exceptions import ConfigError


async def granola_request(path: str) -> object:
    settings = get_settings()
    if not settings.GRANOLA_API_KEY:
        raise ConfigError("GRANOLA_API_KEY not configured")
    base = settings.GRANOLA_API_BASE.rstrip("/")
    url = (
        path if path.startswith("http") else f"{base}{path if path.startswith('/') else '/' + path}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {settings.GRANOLA_API_KEY}",
                "Accept": "application/json",
            },
        )
        text = res.text
        if res.status_code >= 400:
            raise RuntimeError(f"Granola {res.status_code}: {text[:300]}")
        if not text:
            return None
        try:
            return res.json()
        except ValueError:
            return text
