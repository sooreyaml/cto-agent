from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from src.config import get_settings
from src.connections.constants import GITHUB_SCOPES
from src.connections.exceptions import ConnectOAuthFailed, ConnectOAuthNotConfigured
from src.connections.ticket import issue_ticket, parse_ticket

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"


@dataclass(frozen=True)
class GitHubTokenBundle:
    access_token: str
    username: str | None
    scopes: str | None


def oauth_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)


def oauth_redirect_uri() -> str:
    return f"{get_settings().APP_PUBLIC_URL.rstrip('/')}/auth/github/callback"


def issue_connect_url(*, slack_user_id: str | None = None) -> str:
    if not oauth_is_configured():
        raise ConnectOAuthNotConfigured()
    ticket = issue_ticket(slack_user_id=slack_user_id)
    base = get_settings().APP_PUBLIC_URL.rstrip("/")
    return f"{base}/auth/github?{urlencode({'ticket': ticket})}"


def connect_message_markdown(*, slack_user_id: str | None = None) -> str:
    url = issue_connect_url(slack_user_id=slack_user_id)
    return "\n".join(
        [
            "**Connect GitHub** so I can read repos, PRs, and CI, and open issues.",
            "",
            f"[Open GitHub sign-in]({url})",
            "",
            "This link expires in 20 minutes. Come back here after you approve.",
        ]
    )


def authorization_url(ticket: str) -> str:
    if not oauth_is_configured():
        raise ConnectOAuthNotConfigured()
    parse_ticket(ticket)
    settings = get_settings()
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": oauth_redirect_uri(),
        "scope": GITHUB_SCOPES,
        "state": ticket,
        "allow_signup": "false",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str, ticket: str) -> GitHubTokenBundle:
    parse_ticket(ticket)
    if not oauth_is_configured():
        raise ConnectOAuthNotConfigured()
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        token_res = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": oauth_redirect_uri(),
            },
            headers={"Accept": "application/json"},
        )
        if token_res.status_code >= 400:
            raise ConnectOAuthFailed()
        payload: dict[str, Any]
        try:
            payload = token_res.json()
        except ValueError as exc:
            raise ConnectOAuthFailed() from exc
        access = str(payload.get("access_token") or "")
        if not access:
            raise ConnectOAuthFailed()
        user_res = await client.get(
            USER_URL,
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "cto-agent",
            },
        )
        username = None
        if user_res.status_code < 400:
            try:
                login = user_res.json().get("login")
            except ValueError:
                login = None
            if isinstance(login, str) and login:
                username = login
    return GitHubTokenBundle(
        access_token=access,
        username=username,
        scopes=str(payload.get("scope") or GITHUB_SCOPES),
    )
