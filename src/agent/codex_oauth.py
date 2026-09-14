from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from src.connections.repository import get_secret, save_secret
from src.exceptions import ConfigError

logger = logging.getLogger(__name__)

PROVIDER = "openai-codex"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEVICE_USER_CODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
DEVICE_VERIFICATION_URI = "https://auth.openai.com/codex/device"
DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
TOKEN_URL = "https://auth.openai.com/oauth/token"
JWT_AUTH_CLAIM = "https://api.openai.com/auth"
DEVICE_TIMEOUT_S = 15 * 60
REFRESH_MARGIN_S = 5 * 60

_refresh_lock = asyncio.Lock()
_poll_task: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class CodexCredential:
    access_token: str
    refresh_token: str
    expires_at: float
    account_id: str


@dataclass(frozen=True)
class DevicePending:
    device_auth_id: str
    user_code: str
    interval_s: float
    verification_uri: str = DEVICE_VERIFICATION_URI


def connect_message_markdown(pending: DevicePending) -> str:
    url = pending.verification_uri
    code = pending.user_code.strip().upper()
    return "\n".join(
        [
            "**Connect ChatGPT / Codex** so I can fall back to your Plus/Pro (or Codex) "
            "subscription when OpenRouter fails.",
            "",
            f"[Open ChatGPT device login]({url})",
            url,
            "",
            f"Then sign in and enter this code (15 min): **{code}**",
            "",
            "The page can be on your laptop even if Discord is on your phone — type the code "
            "on that browser page, not in the ChatGPT app. Same ChatGPT account as Plus/Pro.",
            "",
            "If it says it could not authorize the device: ChatGPT → Settings → Security → "
            "turn on **Device code authorization**, then say `connect openai` again for a "
            "fresh code. Do not reuse an old tab.",
        ]
    )


def account_id_from_jwt(token: str) -> str:
    parts = token.split(".")
    if len(parts) < 2:
        raise ConfigError("Codex access token is not a JWT")
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    data = json.loads(decoded)
    account_id = str((data.get(JWT_AUTH_CLAIM) or {}).get("chatgpt_account_id") or "").strip()
    if not account_id:
        raise ConfigError("Codex access token has no ChatGPT account id")
    return account_id


def _form(fields: list[tuple[str, str]]) -> str:
    return urlencode(fields)


async def start_device_auth() -> DevicePending:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(DEVICE_USER_CODE_URL, json={"client_id": CLIENT_ID})
        res.raise_for_status()
        data = res.json()
    interval = data.get("interval")
    try:
        interval_s = float(interval)
    except (TypeError, ValueError):
        interval_s = 2.0
    return DevicePending(
        device_auth_id=str(data["device_auth_id"]),
        user_code=str(data["user_code"]),
        interval_s=max(1.0, interval_s),
    )


async def poll_device_auth(pending: DevicePending) -> tuple[str, str]:
    deadline = time.monotonic() + DEVICE_TIMEOUT_S
    interval = pending.interval_s
    async with httpx.AsyncClient(timeout=30) as client:
        while time.monotonic() < deadline:
            res = await client.post(
                DEVICE_TOKEN_URL,
                json={
                    "device_auth_id": pending.device_auth_id,
                    "user_code": pending.user_code,
                },
            )
            if res.status_code == 200:
                data = res.json()
                code = str(data.get("authorization_code") or "")
                verifier = str(data.get("code_verifier") or "")
                if not code or not verifier:
                    raise ConfigError("Codex device login returned an empty authorization code")
                return code, verifier
            error = _error_code(res)
            if error == "slow_down":
                interval += 5
            elif error not in {"deviceauth_authorization_pending", ""} and res.status_code not in {
                403,
                404,
            }:
                raise ConfigError(
                    f"Codex device login failed ({res.status_code}): {res.text[:300]}"
                )
            await asyncio.sleep(interval)
    raise ConfigError("Codex device login timed out. Say connect openai and try again.")


def _error_code(res: httpx.Response) -> str:
    try:
        data = res.json()
    except ValueError:
        return ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, str):
            return err
        if isinstance(err, dict):
            return str(err.get("code") or "")
    return ""


async def exchange_code(authorization_code: str, code_verifier: str) -> CodexCredential:
    return await _token_request(
        [
            ("grant_type", "authorization_code"),
            ("client_id", CLIENT_ID),
            ("code", authorization_code),
            ("code_verifier", code_verifier),
            ("redirect_uri", DEVICE_REDIRECT_URI),
        ]
    )


async def refresh_credential(refresh_token: str) -> CodexCredential:
    return await _token_request(
        [
            ("grant_type", "refresh_token"),
            ("refresh_token", refresh_token),
            ("client_id", CLIENT_ID),
        ]
    )


async def _token_request(fields: list[tuple[str, str]]) -> CodexCredential:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            TOKEN_URL,
            content=_form(fields),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if res.status_code != 200:
            raise ConfigError(f"Codex token request failed ({res.status_code}): {res.text[:300]}")
        data = res.json()
    access = str(data.get("access_token") or "")
    refresh = str(data.get("refresh_token") or "")
    if not access or not refresh:
        raise ConfigError("Codex token response missing access or refresh token")
    expires_in = float(data.get("expires_in") or 3600)
    return CodexCredential(
        access_token=access,
        refresh_token=refresh,
        expires_at=time.time() + expires_in,
        account_id=account_id_from_jwt(access),
    )


async def persist_credential(cred: CodexCredential) -> None:
    await save_secret(
        provider=PROVIDER,
        token=cred.access_token,
        extra={
            "refresh_token": cred.refresh_token,
            "expires_at": cred.expires_at,
            "account_id": cred.account_id,
            "kind": "codex_oauth",
        },
    )


def _from_row(token: str, extra: dict[str, Any]) -> CodexCredential | None:
    refresh = str(extra.get("refresh_token") or "").strip()
    if not token or not refresh:
        return None
    try:
        expires_at = float(extra.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    account_id = str(extra.get("account_id") or "").strip()
    if not account_id:
        try:
            account_id = account_id_from_jwt(token)
        except ConfigError:
            return None
    return CodexCredential(
        access_token=token,
        refresh_token=refresh,
        expires_at=expires_at,
        account_id=account_id,
    )


async def load_credential() -> CodexCredential | None:
    row = await get_secret(PROVIDER)
    if row is None:
        return None
    extra: dict[str, Any] = {}
    if row.extra:
        try:
            parsed = json.loads(row.extra)
            if isinstance(parsed, dict):
                extra = parsed
        except ValueError:
            return None
    return _from_row(row.token, extra)


async def resolve_credential(*, force_refresh: bool = False) -> CodexCredential:
    async with _refresh_lock:
        cred = await load_credential()
        if cred is None:
            raise ConfigError(
                "ChatGPT / Codex is not connected. Say “connect openai” in Discord and "
                "enter the device code. Do not paste an OpenAI API key."
            )
        if force_refresh or time.time() + REFRESH_MARGIN_S >= cred.expires_at:
            cred = await refresh_credential(cred.refresh_token)
            await persist_credential(cred)
        return cred


def request_headers(cred: CodexCredential) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cred.access_token}",
        "ChatGPT-Account-ID": cred.account_id,
        "originator": "cto-agent",
        "User-Agent": "CTOAgent/0.1.0",
        "OpenAI-Beta": "responses=experimental",
    }


async def complete_device_login(pending: DevicePending) -> CodexCredential:
    code, verifier = await poll_device_auth(pending)
    cred = await exchange_code(code, verifier)
    await persist_credential(cred)
    return cred


def spawn_login_poll(pending: DevicePending, on_done, on_error) -> None:
    global _poll_task

    async def _run() -> None:
        try:
            cred = await complete_device_login(pending)
            await on_done(cred)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.exception("codex device login failed")
            await on_error(err)

    if _poll_task is not None and not _poll_task.done():
        _poll_task.cancel()
    _poll_task = asyncio.create_task(_run())
