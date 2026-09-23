"""Metadata-only daily brief run repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.brief.models import BriefRun
from src.connections.redact import redact_secrets
from src.database import async_session_factory


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _text(value: object, max_chars: int) -> str:
    return redact_secrets(str(value or "").strip())[:max_chars]


def _bounded_int(value: object, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _owner(value: object) -> str:
    owner = _text(value, 120)
    if not owner:
        raise ValueError("owner_id is required")
    return owner


def _brief_to_dict(row: BriefRun) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "owner_id": row.owner_id,
        "run_date": row.run_date.isoformat(),
        "timezone": row.timezone,
        "source_health": row.source_health or {},
        "signal_count": row.signal_count,
        "action_count": row.action_count,
        "evidence_urls": row.evidence_urls or [],
        "render_status": row.render_status,
        "delivery_status": row.delivery_status,
        "error_type": row.error_type,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
    }


async def create_brief_run(
    owner_id: str,
    *,
    run_date: datetime,
    timezone: str,
    source_health: dict[str, Any],
    signal_count: int,
    action_count: int,
    evidence_urls: list[str],
) -> dict[str, Any]:
    row = BriefRun(
        owner_id=_owner(owner_id),
        run_date=run_date,
        timezone=_text(timezone, 80) or "UTC",
        source_health=source_health,
        signal_count=_bounded_int(signal_count),
        action_count=_bounded_int(action_count),
        evidence_urls=[_text(url, 500) for url in evidence_urls[:20] if str(url or "").strip()],
        render_status="pending",
        delivery_status="pending",
    )
    async with async_session_factory() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _brief_to_dict(row)


async def finish_brief_run(
    brief_run_id: str,
    *,
    render_status: str,
    delivery_status: str,
    error_type: str | None = None,
    delivered_at: datetime | None = None,
) -> dict[str, Any] | None:
    try:
        parsed = UUID(str(brief_run_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("brief_run_id must be a UUID") from exc
    async with async_session_factory() as session:
        row = await session.scalar(select(BriefRun).where(BriefRun.id == parsed))
        if row is None:
            return None
        row.render_status = _text(render_status, 40) or "unknown"
        row.delivery_status = _text(delivery_status, 40) or "unknown"
        row.error_type = _text(error_type, 120) or None
        row.delivered_at = delivered_at or (_utcnow() if delivery_status == "sent" else None)
        await session.commit()
        await session.refresh(row)
        return _brief_to_dict(row)
