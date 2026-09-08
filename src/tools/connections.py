from typing import Any

from src.connections.catalog import catalog_public, get_provider, normalize_provider
from src.connections.github_oauth import (
    connect_message_markdown as github_connect_message,
)
from src.connections.github_oauth import oauth_is_configured as github_oauth_is_configured
from src.connections.granola_oauth import connect_message_markdown as granola_connect_message
from src.connections.http import connected_request
from src.connections.repository import delete_secret, list_secrets, save_secret
from src.google.service import connect_message_markdown as google_connect_message
from src.google.service import oauth_is_configured as google_oauth_is_configured


async def _catalog(_args: dict[str, Any]) -> dict[str, Any]:
    return {"providers": catalog_public()}


async def _connect(args: dict[str, Any]) -> dict[str, Any]:
    provider = normalize_provider(args.get("provider"))
    if provider == "google":
        if not google_oauth_is_configured():
            raise ValueError("Google OAuth is not configured (GOOGLE_CLIENT_ID / SECRET).")
        return {"provider": "google", "discord_markdown": google_connect_message()}
    if provider == "github":
        if not github_oauth_is_configured():
            raise ValueError(
                "GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET."
            )
        return {"provider": "github", "discord_markdown": github_connect_message()}
    if provider == "granola":
        return {"provider": "granola", "discord_markdown": granola_connect_message()}
    spec = get_provider(provider)
    return {
        "provider": provider,
        "auth": spec.get("auth") or "bearer",
        "how": spec["how"],
        "hint": (
            "This tool uses an API key, not browser OAuth. Ask the user to paste the key "
            "in this DM, then connections_save. Do not tell them to edit .env."
        ),
    }


async def _list(_args: dict[str, Any]) -> dict[str, Any]:
    return {"connections": await list_secrets()}


async def _save(args: dict[str, Any]) -> dict[str, Any]:
    extra = args.get("extra")
    if extra is not None and not isinstance(extra, dict):
        extra = None
    saved = await save_secret(
        provider=str(args.get("provider") or ""),
        token=str(args.get("token") or ""),
        label=str(args.get("label") or ""),
        extra=extra,
    )
    spec = get_provider(saved["provider"])
    return {
        "ok": True,
        "saved": saved,
        "hint": f"{spec['name']} is connected. Do not repeat the token. Use connections_request or the native tools.",
    }


async def _delete(args: dict[str, Any]) -> dict[str, Any]:
    removed = await delete_secret(str(args.get("provider") or ""), str(args.get("label") or ""))
    return {"ok": True, "removed": removed}


async def _request(args: dict[str, Any]) -> dict[str, Any]:
    return await connected_request(
        provider=str(args.get("provider") or ""),
        method=str(args.get("method") or "GET"),
        path=str(args.get("path") or ""),
        query=args.get("query") if isinstance(args.get("query"), dict) else None,
        json_body=args.get("json"),
    )


connections_tools = {
    "connections_catalog": {
        "spec": {
            "type": "function",
            "function": {
                "name": "connections_catalog",
                "description": (
                    "List tools the user can connect from Discord. Google, GitHub, and Granola "
                    "use browser OAuth (connections_connect). Others still take an API key. "
                    "Never tell them to edit .env."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "handler": _catalog,
    },
    "connections_connect": {
        "spec": {
            "type": "function",
            "function": {
                "name": "connections_connect",
                "description": (
                    "Start a browser OAuth connect for google, github, or granola. "
                    "Send discord_markdown to the user. They can also say connect github / "
                    "connect granola / connect google. Never ask them to paste a GitHub PAT "
                    "or Granola API key."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "google, github, or granola (other providers explain API-key flow)",
                        },
                    },
                    "required": ["provider"],
                },
            },
        },
        "handler": _connect,
    },
    "connections_list": {
        "spec": {
            "type": "function",
            "function": {
                "name": "connections_list",
                "description": "List connected tools (provider + label only; tokens are never returned).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "handler": _list,
    },
    "connections_save": {
        "spec": {
            "type": "function",
            "function": {
                "name": "connections_save",
                "description": (
                    "Store an API token the user pasted in Discord for key-based tools "
                    "(Linear, Sentry, Coolify, …). Do not use this for GitHub or Granola — "
                    "those are browser OAuth via connections_connect. Do not echo the token."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "github, granola, linear, sentry, vercel, coolify, tavily, stripe, cloudflare, notion, slack",
                        },
                        "token": {"type": "string"},
                        "label": {
                            "type": "string",
                            "description": "Optional nickname if they connect more than one of the same tool",
                        },
                        "extra": {
                            "type": "object",
                            "description": "Optional username, org, team_id, or base_url (Coolify)",
                        },
                    },
                    "required": ["provider", "token"],
                },
            },
        },
        "handler": _save,
    },
    "connections_delete": {
        "spec": {
            "type": "function",
            "function": {
                "name": "connections_delete",
                "description": "Remove a stored API connection.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["provider"],
                },
            },
        },
        "handler": _delete,
    },
    "connections_request": {
        "spec": {
            "type": "function",
            "function": {
                "name": "connections_request",
                "description": (
                    "Call a connected tool's HTTPS API (Bearer token). "
                    "path is relative (e.g. /issues). Host is fixed to that provider. "
                    "Use for Linear, Sentry, Coolify, etc. Prefer native GitHub/Gmail tools when they exist."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PATCH", "PUT", "DELETE"],
                        },
                        "path": {"type": "string"},
                        "query": {"type": "object"},
                        "json": {"type": "object"},
                    },
                    "required": ["provider", "path"],
                },
            },
        },
        "handler": _request,
    },
}
