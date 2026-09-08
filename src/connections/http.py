from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from src.connections.catalog import get_provider
from src.connections.repository import resolve_extra, resolve_token
from src.exceptions import ConfigError


def _base_url(spec: dict[str, Any], extra: dict[str, Any]) -> str:
    raw = extra.get("base_url") or spec.get("base_url")
    if not raw:
        raise ConfigError(f"{spec['name']} needs a base_url — send it when connecting")
    return str(raw).rstrip("/") + "/"


def _safe_url(base: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        parsed = urlparse(path)
        allowed = urlparse(base)
        if parsed.scheme != "https" or parsed.netloc != allowed.netloc:
            raise ConfigError("path must be a relative API path on the connected host")
        return path
    return urljoin(base, path.lstrip("/"))


async def connected_request(
    *,
    provider: str,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    json_body: Any = None,
) -> dict[str, Any]:
    spec = get_provider(provider)
    token = await resolve_token(provider)
    if not token:
        if spec.get("auth") == "oauth":
            raise ConfigError(
                f"{spec['name']} is not connected. Ask the user to say “connect {provider}” "
                "in Discord and open the sign-in link. Do not tell them to edit .env."
            )
        raise ConfigError(
            f"{spec['name']} is not connected. Ask the user to paste an API key in this DM "
            f"({spec['how']}), then call connections_save. Do not tell them to edit .env."
        )
    extra = await resolve_extra(provider)
    base = _base_url(spec, extra)
    verb = (method or "GET").upper()
    if verb not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
        raise ConfigError("method must be GET, POST, PATCH, PUT, or DELETE")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        **(spec.get("headers") or {}),
    }
    url = _safe_url(base, path)
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.request(
            verb,
            url,
            params=query or None,
            json=json_body if verb != "GET" else None,
            headers=headers,
        )
    body: Any
    try:
        body = res.json()
    except ValueError:
        body = res.text[:4000]
    return {
        "status": res.status_code,
        "provider": provider,
        "ok": res.status_code < 400,
        "body": body,
    }
