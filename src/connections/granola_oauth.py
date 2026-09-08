from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from src.config import get_settings
from src.connections.constants import (
    GRANOLA_AUTHORIZE,
    GRANOLA_MCP_URL,
    GRANOLA_REGISTER,
    GRANOLA_SCOPES,
    GRANOLA_TOKEN,
)
from src.connections.exceptions import ConnectOAuthFailed, ConnectOAuthInvalidTicket
from src.connections.repository import resolve_extra
from src.connections.ticket import issue_ticket, parse_ticket, pkce_challenge

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GranolaTokenBundle:
    access_token: str
    refresh_token: str | None
    client_id: str
    token_expiry: datetime | None
    email: str | None
    scopes: str | None


def oauth_redirect_uri() -> str:
    return f"{get_settings().APP_PUBLIC_URL.rstrip('/')}/auth/granola/callback"


def issue_connect_url(*, slack_user_id: str | None = None) -> str:
    ticket = issue_ticket(slack_user_id=slack_user_id)
    base = get_settings().APP_PUBLIC_URL.rstrip("/")
    return f"{base}/auth/granola?{urlencode({'ticket': ticket})}"


def connect_message_markdown(*, slack_user_id: str | None = None) -> str:
    url = issue_connect_url(slack_user_id=slack_user_id)
    return "\n".join(
        [
            "**Connect Granola** so I can read your meeting notes. Sign in in the browser — "
            "no API key.",
            "",
            f"[Open Granola sign-in]({url})",
            "",
            "This link expires in 20 minutes. Come back here after you approve.",
        ]
    )


def register_payload() -> dict[str, Any]:
    return {
        "client_name": "CTO Agent",
        "redirect_uris": [oauth_redirect_uri()],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": "web",
        "scope": GRANOLA_SCOPES,
    }


async def register_client() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            GRANOLA_REGISTER,
            json=register_payload(),
            headers={"Accept": "application/json"},
        )
    if res.status_code >= 400:
        logger.warning("granola DCR failed status=%s body=%s", res.status_code, res.text[:300])
        raise ConnectOAuthFailed()
    try:
        data = res.json()
    except ValueError as exc:
        raise ConnectOAuthFailed() from exc
    client_id = data.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise ConnectOAuthFailed()
    return client_id


async def resolve_client_id() -> str:
    extra = await resolve_extra("granola")
    existing = extra.get("client_id")
    if extra.get("kind") == "mcp_oauth" and isinstance(existing, str) and existing:
        return existing
    return await register_client()


def authorization_url(ticket: str) -> str:
    parsed = parse_ticket(ticket)
    if not parsed.client_id:
        raise ConnectOAuthInvalidTicket()
    params = {
        "response_type": "code",
        "client_id": parsed.client_id,
        "redirect_uri": oauth_redirect_uri(),
        "state": ticket,
        "code_challenge": pkce_challenge(parsed.code_verifier),
        "code_challenge_method": "S256",
        "scope": GRANOLA_SCOPES,
        "resource": GRANOLA_MCP_URL,
    }
    return f"{GRANOLA_AUTHORIZE}?{urlencode(params)}"


async def start_authorization_url(ticket: str) -> str:
    parsed = parse_ticket(ticket)
    client_id = parsed.client_id or await resolve_client_id()
    next_ticket = issue_ticket(
        slack_user_id=parsed.slack_user_id,
        code_verifier=parsed.code_verifier,
        client_id=client_id,
    )
    return authorization_url(next_ticket)


def _email_from_id_token(id_token: str | None) -> str | None:
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        email = data.get("email")
        return email if isinstance(email, str) else None
    except Exception:
        return None


def _expiry(seconds: object) -> datetime | None:
    try:
        ttl = int(seconds)
    except (TypeError, ValueError):
        return None
    if ttl <= 0:
        return None
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=ttl)


async def _token_request(data: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            GRANOLA_TOKEN,
            data=data,
            headers={"Accept": "application/json"},
        )
    if res.status_code >= 400:
        logger.warning("granola token failed status=%s body=%s", res.status_code, res.text[:300])
        raise ConnectOAuthFailed()
    try:
        payload = res.json()
    except ValueError as exc:
        raise ConnectOAuthFailed() from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ConnectOAuthFailed()
    return payload


def _bundle(payload: dict[str, Any], client_id: str) -> GranolaTokenBundle:
    return GranolaTokenBundle(
        access_token=str(payload["access_token"]),
        refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
        client_id=client_id,
        token_expiry=_expiry(payload.get("expires_in")),
        email=_email_from_id_token(
            payload.get("id_token") if isinstance(payload.get("id_token"), str) else None
        ),
        scopes=str(payload["scope"]) if payload.get("scope") else GRANOLA_SCOPES,
    )


async def exchange_code(code: str, ticket: str) -> GranolaTokenBundle:
    parsed = parse_ticket(ticket)
    if not parsed.client_id:
        raise ConnectOAuthInvalidTicket()
    payload = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": oauth_redirect_uri(),
            "client_id": parsed.client_id,
            "code_verifier": parsed.code_verifier,
            "resource": GRANOLA_MCP_URL,
        }
    )
    return _bundle(payload, parsed.client_id)


async def refresh_access_token(*, refresh_token: str, client_id: str) -> GranolaTokenBundle:
    payload = await _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "resource": GRANOLA_MCP_URL,
        }
    )
    if not payload.get("refresh_token"):
        payload["refresh_token"] = refresh_token
    return _bundle(payload, client_id)
