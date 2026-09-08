from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from src.config import get_settings
from src.connections.granola_oauth import refresh_access_token
from src.connections.repository import resolve_extra, resolve_token, save_secret
from src.exceptions import ConfigError
from src.integrations.granola_mcp import call_granola_tool, path_to_mcp

_NOT_CONNECTED = (
    "Granola is not connected. Ask the user to say “connect granola” in Discord "
    "and open the sign-in link. Do not tell them to edit .env."
)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _expiry_soon(raw: object) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    try:
        expiry = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return _naive_utc(expiry) <= datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=2)


async def _persist_bundle(bundle: Any, extra: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    merged = {
        **extra,
        "kind": "mcp_oauth",
        "client_id": bundle.client_id,
        "refresh_token": bundle.refresh_token or extra.get("refresh_token"),
        "token_expiry": bundle.token_expiry.isoformat() if bundle.token_expiry else None,
        "email": bundle.email or extra.get("email"),
        "scopes": bundle.scopes or extra.get("scopes"),
        "mcp_url": extra.get("mcp_url") or "https://mcp.granola.ai/mcp",
    }
    await save_secret(provider="granola", token=bundle.access_token, extra=merged)
    return bundle.access_token, merged


async def ready_granola() -> tuple[str, dict[str, Any]]:
    token = await resolve_token("granola")
    extra = await resolve_extra("granola")
    if not token:
        raise ConfigError(_NOT_CONNECTED)
    if extra.get("kind") != "mcp_oauth":
        return token, extra
    refresh = extra.get("refresh_token")
    client_id = extra.get("client_id")
    if (
        _expiry_soon(extra.get("token_expiry"))
        and isinstance(refresh, str)
        and refresh
        and isinstance(client_id, str)
        and client_id
    ):
        bundle = await refresh_access_token(refresh_token=refresh, client_id=client_id)
        return await _persist_bundle(bundle, extra)
    return token, extra


async def _rest(path: str, token: str, extra: dict[str, Any]) -> object:
    base = str(extra.get("base_url") or get_settings().GRANOLA_API_BASE).rstrip("/")
    url = (
        path if path.startswith("http") else f"{base}{path if path.startswith('/') else '/' + path}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
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


async def _mcp(name: str, args: dict[str, Any]) -> object:
    token, extra = await ready_granola()
    try:
        return await call_granola_tool(token, extra, name, args)
    except RuntimeError as err:
        if "401" not in str(err):
            raise
        refresh = extra.get("refresh_token")
        client_id = extra.get("client_id")
        if extra.get("kind") != "mcp_oauth" or not refresh or not client_id:
            raise
        bundle = await refresh_access_token(refresh_token=str(refresh), client_id=str(client_id))
        token, extra = await _persist_bundle(bundle, extra)
        return await call_granola_tool(token, extra, name, args)


async def granola_list_meetings(limit: int = 10) -> object:
    token, extra = await ready_granola()
    if extra.get("kind") == "mcp_oauth":
        return await _mcp("list_meetings", {"limit": limit, "range": "last_30_days"})
    return await _rest(f"/meetings?limit={limit}", token, extra)


async def granola_get_meeting(meeting_id: str) -> object:
    token, extra = await ready_granola()
    if extra.get("kind") == "mcp_oauth":
        return await _mcp("get_meetings", {"ids": [meeting_id], "id": meeting_id})
    from urllib.parse import quote

    return await _rest(f"/meetings/{quote(meeting_id, safe='')}", token, extra)


async def granola_search(query: str, limit: int = 10) -> object:
    token, extra = await ready_granola()
    if extra.get("kind") == "mcp_oauth":
        return await _mcp("query_granola_meetings", {"query": query, "limit": limit})
    from urllib.parse import quote

    return await _rest(f"/search?q={quote(query)}&limit={limit}", token, extra)


async def granola_request(path: str) -> object:
    token, extra = await ready_granola()
    if extra.get("kind") == "mcp_oauth":
        name, args = path_to_mcp(path)
        return await _mcp(name, args)
    parsed = urlparse(path if "://" in path else f"https://granola.local{path}")
    if parsed.path.startswith("/search"):
        query = parse_qs(parsed.query)
        q = (query.get("q") or query.get("query") or [""])[0]
        limit = int((query.get("limit") or ["10"])[0])
        return await granola_search(q, limit)
    return await _rest(path, token, extra)
