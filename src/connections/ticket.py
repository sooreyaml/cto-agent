from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from src.config import get_settings
from src.connections.constants import TICKET_TTL_SECONDS
from src.connections.exceptions import ConnectOAuthInvalidTicket


@dataclass(frozen=True)
class ConnectTicket:
    slack_user_id: str
    code_verifier: str
    client_id: str | None = None


def _ticket_secret() -> bytes:
    return get_settings().DISCORD_BOT_TOKEN.encode("utf-8")


def _owner_user_id() -> str:
    return get_settings().owner_user_id


def pkce_verifier() -> str:
    return secrets.token_urlsafe(64).rstrip("=")


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_ticket(
    *,
    slack_user_id: str | None = None,
    code_verifier: str | None = None,
    client_id: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "cid": client_id or None,
            "exp": int(time.time()) + TICKET_TTL_SECONDS,
            "n": secrets.token_urlsafe(12),
            "uid": slack_user_id or _owner_user_id(),
            "v": code_verifier or pkce_verifier(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    sig = hmac.new(_ticket_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def parse_ticket(ticket: str) -> ConnectTicket:
    padded = ticket + "=" * (-len(ticket) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConnectOAuthInvalidTicket() from exc
    payload, sep, sig = raw.rpartition(":")
    if not sep or not payload or not sig:
        raise ConnectOAuthInvalidTicket()
    expected = hmac.new(_ticket_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ConnectOAuthInvalidTicket()
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ConnectOAuthInvalidTicket() from exc
    if not isinstance(data, dict):
        raise ConnectOAuthInvalidTicket()
    try:
        expires_at = int(data["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConnectOAuthInvalidTicket() from exc
    if expires_at < int(time.time()):
        raise ConnectOAuthInvalidTicket()
    uid = str(data.get("uid") or "")
    verifier = str(data.get("v") or "")
    if not uid or not verifier:
        raise ConnectOAuthInvalidTicket()
    if uid != _owner_user_id():
        raise ConnectOAuthInvalidTicket()
    client_id = data.get("cid")
    return ConnectTicket(
        slack_user_id=uid,
        code_verifier=verifier,
        client_id=str(client_id) if client_id else None,
    )
