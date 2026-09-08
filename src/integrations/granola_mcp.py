from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from src.connections.constants import GRANOLA_MCP_URL
from src.exceptions import ConfigError

logger = logging.getLogger(__name__)

PROTOCOL = "2025-03-26"
_TOOL_ALIASES = {
    "list_meetings": ("list_meetings",),
    "get_meetings": ("get_meetings", "get_meeting"),
    "query_granola_meetings": ("query_granola_meetings", "search_meetings"),
}

_ARG_ALIASES = {
    "limit": ("limit", "max_results", "n", "page_size"),
    "query": ("query", "q", "question", "prompt"),
    "id": ("id", "meeting_id", "note_id"),
    "ids": ("meeting_ids", "ids", "id", "meeting_id"),
    "range": ("range", "time_range"),
}


def _parse_sse(text: str) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            parsed = json.loads(data)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            last = parsed
    if last is None:
        raise RuntimeError("Granola MCP returned an empty event stream")
    return last


def _rpc_result(response: httpx.Response) -> Any:
    ctype = response.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        payload = _parse_sse(response.text)
    else:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Granola MCP {response.status_code}: {response.text[:300]}"
            ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Granola MCP returned a non-object")
    if payload.get("error"):
        err = payload["error"]
        message = err.get("message") if isinstance(err, dict) else err
        raise RuntimeError(f"Granola MCP error: {message}")
    return payload.get("result")


class GranolaMcpClient:
    def __init__(self, token: str, mcp_url: str = GRANOLA_MCP_URL) -> None:
        self._token = token
        self._url = mcp_url
        self._session_id: str | None = None
        self._rpc_id = 0
        self._tools: dict[str, dict[str, Any]] | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
        res = await client.post(self._url, json=body, headers=self._headers())
        session = res.headers.get("mcp-session-id") or res.headers.get("Mcp-Session-Id")
        if session:
            self._session_id = session
        if res.status_code >= 400:
            raise RuntimeError(f"Granola MCP {res.status_code}: {res.text[:300]}")
        return res

    async def initialize(self, client: httpx.AsyncClient) -> None:
        self._rpc_id += 1
        res = await self._post(
            client,
            {
                "jsonrpc": "2.0",
                "id": self._rpc_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "cto-agent", "version": "0.1.0"},
                },
            },
        )
        _rpc_result(res)
        await client.post(
            self._url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._headers(),
        )

    async def list_tools(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        if self._tools is not None:
            return self._tools
        self._rpc_id += 1
        res = await self._post(
            client,
            {"jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/list", "params": {}},
        )
        result = _rpc_result(res) or {}
        tools = result.get("tools") if isinstance(result, dict) else None
        mapped: dict[str, dict[str, Any]] = {}
        for tool in tools or []:
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                mapped[tool["name"]] = tool
        self._tools = mapped
        return mapped

    def _resolve_tool(self, tools: dict[str, dict[str, Any]], wanted: str) -> dict[str, Any]:
        for name in _TOOL_ALIASES.get(wanted, (wanted,)):
            if name in tools:
                return tools[name]
        for name, tool in tools.items():
            if wanted in name:
                return tool
        known = ", ".join(sorted(tools)) or "(none)"
        raise ConfigError(f"Granola MCP has no {wanted} tool. Available: {known}")

    def _bind(self, schema: dict[str, Any] | None, args: dict[str, Any]) -> dict[str, Any]:
        props = (schema or {}).get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict) or not props:
            return {key: value for key, value in args.items() if value is not None}
        bound: dict[str, Any] = {}
        for key, value in args.items():
            if value is None:
                continue
            for alias in _ARG_ALIASES.get(key, (key,)):
                if alias in props:
                    spec = props[alias]
                    types = spec.get("type") if isinstance(spec, dict) else None
                    if types == "array" or (isinstance(types, list) and "array" in types):
                        bound[alias] = value if isinstance(value, list) else [value]
                    else:
                        bound[alias] = value[0] if isinstance(value, list) and value else value
                    break
        return bound

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            await self.initialize(client)
            tools = await self.list_tools(client)
            tool = self._resolve_tool(tools, name)
            schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
            self._rpc_id += 1
            res = await self._post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": self._rpc_id,
                    "method": "tools/call",
                    "params": {
                        "name": tool["name"],
                        "arguments": self._bind(schema, args),
                    },
                },
            )
            return _rpc_result(res)


async def call_granola_tool(
    token: str, extra: dict[str, Any], name: str, args: dict[str, Any]
) -> Any:
    url = str(extra.get("mcp_url") or GRANOLA_MCP_URL)
    return await GranolaMcpClient(token, url).call_tool(name, args)


def path_to_mcp(path: str) -> tuple[str, dict[str, Any]]:
    parsed = urlparse(path if "://" in path else f"https://granola.local{path}")
    query = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
    route = parsed.path.rstrip("/")
    if route.startswith("/search"):
        return "query_granola_meetings", {
            "query": query.get("q") or query.get("query") or "",
            "limit": _int(query.get("limit"), 10),
        }
    if route.startswith("/meetings/"):
        meeting_id = route.split("/meetings/", 1)[1]
        return "get_meetings", {"ids": [meeting_id], "id": meeting_id}
    return "list_meetings", {
        "limit": _int(query.get("limit"), 10),
        "range": "last_30_days",
    }


def _int(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default
