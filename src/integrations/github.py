import httpx

from src.config import get_settings
from src.exceptions import ConfigError


def github_headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.GITHUB_PAT:
        raise ConfigError("GITHUB_PAT not configured")
    return {
        "Authorization": f"Bearer {settings.GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cto-agent",
    }


def github_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.github.com",
        headers=github_headers(),
        timeout=30,
    )
