import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from src.config import get_settings
from src.connections.catalog import get_provider, normalize_provider
from src.connections.constants import HIDDEN_EXTRA_KEYS
from src.connections.models import ConnectedSecret
from src.database import async_session_factory
from src.exceptions import ConfigError


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _label(raw: object) -> str:
    return str(raw or "").strip()


def _parse_extra(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _dump_extra(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    return json.dumps(data)


def public_extra(extra: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in extra.items() if key not in HIDDEN_EXTRA_KEYS}


def _public(row: ConnectedSecret) -> dict[str, Any]:
    extra = public_extra(_parse_extra(row.extra))
    return {
        "id": str(row.id),
        "provider": row.provider,
        "label": row.label or None,
        "extra": extra,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def validate_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError("base_url must be an https URL")
    return url.rstrip("/")


async def list_secrets() -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(ConnectedSecret).order_by(
                        ConnectedSecret.provider.asc(), ConnectedSecret.label.asc()
                    )
                )
            ).all()
        )
        return [_public(row) for row in rows]


async def get_secret(provider: str, label: str = "") -> ConnectedSecret | None:
    key = normalize_provider(provider)
    tag = _label(label)
    async with async_session_factory() as session:
        return await session.scalar(
            select(ConnectedSecret).where(
                ConnectedSecret.provider == key, ConnectedSecret.label == tag
            )
        )


async def resolve_token(provider: str, label: str = "") -> str | None:
    row = await get_secret(provider, label)
    if row is not None:
        return row.token
    settings = get_settings()
    if normalize_provider(provider) == "github" and settings.GITHUB_PAT:
        return settings.GITHUB_PAT
    if normalize_provider(provider) == "granola" and settings.GRANOLA_API_KEY:
        return settings.GRANOLA_API_KEY
    return None


async def resolve_extra(provider: str, label: str = "") -> dict[str, Any]:
    row = await get_secret(provider, label)
    extra = _parse_extra(row.extra) if row else {}
    settings = get_settings()
    if normalize_provider(provider) == "github" and settings.GITHUB_USERNAME:
        extra.setdefault("username", settings.GITHUB_USERNAME)
    if normalize_provider(provider) == "granola" and settings.GRANOLA_API_BASE:
        extra.setdefault("base_url", settings.GRANOLA_API_BASE)
    return extra


async def save_secret(
    *,
    provider: str,
    token: str,
    label: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = normalize_provider(provider)
    spec = get_provider(key)
    secret = token.strip()
    if len(secret) < 8:
        raise ConfigError("token is too short")
    tag = _label(label)
    payload = {k: v for k, v in (extra or {}).items() if v not in (None, "")}
    if spec.get("requires_base_url") and not payload.get("base_url"):
        raise ConfigError(f"{spec['name']} needs extra.base_url (https://…)")
    if payload.get("base_url"):
        payload["base_url"] = validate_base_url(str(payload["base_url"]))
    now = _utcnow()
    async with async_session_factory() as session:
        row = await session.scalar(
            select(ConnectedSecret).where(
                ConnectedSecret.provider == key, ConnectedSecret.label == tag
            )
        )
        if row is None:
            row = ConnectedSecret(
                provider=key,
                label=tag,
                token=secret,
                extra=_dump_extra(payload),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.token = secret
            if payload:
                merged = _parse_extra(row.extra)
                merged.update(payload)
                row.extra = _dump_extra(merged)
            row.updated_at = now
        await session.commit()
        await session.refresh(row)
        return _public(row)


async def delete_secret(provider: str, label: str = "") -> bool:
    key = normalize_provider(provider)
    tag = _label(label)
    async with async_session_factory() as session:
        row = await session.scalar(
            select(ConnectedSecret).where(
                ConnectedSecret.provider == key, ConnectedSecret.label == tag
            )
        )
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
