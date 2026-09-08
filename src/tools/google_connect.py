from typing import Any

from src.config import get_settings
from src.google.exceptions import GoogleOAuthNotConfigured
from src.google.service import (
    connect_message_markdown,
    delete_account,
    env_refresh_rejected,
    issue_connect_url,
    label_account,
    list_accounts,
    load_account,
    oauth_is_configured,
    set_default_account,
)
from src.integrations.google import invalidate_google_credentials


async def _connect_link(_args: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not oauth_is_configured():
        raise GoogleOAuthNotConfigured()
    accounts = await list_accounts()
    env_fallback = bool(settings.GOOGLE_REFRESH_TOKEN) and not env_refresh_rejected()
    url = issue_connect_url()
    default = next(
        (item for item in accounts if item.get("is_default")), accounts[0] if accounts else None
    )
    email = (default.get("email") if default else None) or settings.GOOGLE_USER_EMAIL or None
    return {
        "connected": bool(accounts) or env_fallback,
        "email": email,
        "accounts": accounts,
        "connect_url": url,
        "discord_markdown": connect_message_markdown(),
    }


async def _manage(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "list").strip()
    account = str(args.get("account") or "").strip()
    if action == "list":
        return {"accounts": await list_accounts()}
    if action == "default":
        if not account:
            raise ValueError("account is required to set the default")
        saved = await set_default_account(account)
        invalidate_google_credentials()
        return {"ok": True, "accounts": await list_accounts(), "default": saved.email}
    if action == "label":
        if not account:
            raise ValueError("account is required to set a label")
        saved = await label_account(account, str(args.get("label") or ""))
        return {"ok": True, "account": {"email": saved.email, "label": saved.label}}
    if action == "disconnect":
        if not account:
            raise ValueError("account is required to disconnect")
        existing = await load_account(account)
        removed = await delete_account(account)
        invalidate_google_credentials(existing.key if existing else account)
        return {"ok": True, "removed": removed, "accounts": await list_accounts()}
    raise ValueError(f"Unknown action: {action}")


google_connect_tools = {
    "google_connect_link": {
        "spec": {
            "type": "function",
            "function": {
                "name": "google_connect_link",
                "description": (
                    "Get a Google connect URL and list every connected account. "
                    "Use to add another Google account (work + personal) or when tools fail. "
                    "Send discord_markdown or [Open Google sign-in](connect_url) to the user."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "handler": _connect_link,
    },
    "google_manage_account": {
        "spec": {
            "type": "function",
            "function": {
                "name": "google_manage_account",
                "description": (
                    "List, label, set default, or disconnect a connected Google account. "
                    "account is an email, label, or id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "default", "label", "disconnect"],
                        },
                        "account": {"type": "string"},
                        "label": {
                            "type": "string",
                            "description": "Nickname such as work or personal (action=label)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        "handler": _manage,
    },
}
