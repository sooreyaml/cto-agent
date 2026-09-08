from typing import Any

from src.config import get_settings
from src.google.exceptions import GoogleOAuthNotConfigured
from src.google.service import (
    connect_message_markdown,
    env_refresh_rejected,
    issue_connect_url,
    load_account,
    oauth_is_configured,
)


async def _connect_link(_args: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not oauth_is_configured():
        raise GoogleOAuthNotConfigured()
    account = await load_account()
    env_fallback = bool(settings.GOOGLE_REFRESH_TOKEN) and not env_refresh_rejected()
    url = issue_connect_url()
    email = (account.email if account else None) or settings.GOOGLE_USER_EMAIL or None
    return {
        "connected": account is not None or env_fallback,
        "email": email,
        "connect_url": url,
        "discord_markdown": connect_message_markdown(),
    }


google_connect_tools = {
    "google_connect_link": {
        "spec": {
            "type": "function",
            "function": {
                "name": "google_connect_link",
                "description": (
                    "Get a one-click Google connect URL for Gmail and Calendar, plus connection status. "
                    "Use when Google tools fail, the user asks to connect/reconnect Google, or status is unknown. "
                    "Send discord_markdown or [Open Google sign-in](connect_url) to the user."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "handler": _connect_link,
    },
}
