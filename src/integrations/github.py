from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from src.connections.repository import resolve_token
from src.exceptions import ConfigError


async def github_headers() -> dict[str, str]:
    token = await resolve_token("github")
    if not token:
        raise ConfigError(
            "GitHub is not connected. Ask the user to say “connect github” in Discord "
            "and open the sign-in link. Do not tell them to edit .env."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cto-agent",
    }


@asynccontextmanager
async def github_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        headers=await github_headers(),
        timeout=30,
    ) as client:
        yield client
