"""Durable metadata for CI incidents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from src.ci.intelligence import SEVERITY_ORDER, classify_ci_severity, incident_evidence
from src.ci.models import CIIncident
from src.connections.redact import redact_secrets
from src.database import async_session_factory

INCIDENT_OPEN = "open"
INCIDENT_ACKNOWLEDGED = "acknowledged"
INCIDENT_RESOLVED = "resolved"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _text(value: object, max_chars: int) -> str:
    return redact_secrets(str(value or "").strip())[:max_chars]


def _bounded_int(
    value: object,
    default: int,
    *,
    minimum: int = 0,
    maximum: int = 50,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _owner(value: object) -> str:
    owner = _text(value, 120)
    if not owner:
        raise ValueError("owner_id is required")
    return owner


def _external_id(value: object) -> str:
    external_id = _text(value, 240)
    if not external_id:
        raise ValueError("external_id is required")
    return external_id


def _incident_to_dict(row: CIIncident) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "owner_id": row.owner_id,
        "external_id": row.external_id,
        "repository": row.repository,
        "workflow": row.workflow_name,
        "branch": row.branch,
        "run_number": row.run_number,
        "status": row.status,
        "severity": row.severity,
        "failure_streak": row.failure_streak,
        "url": row.url,
        "evidence": row.evidence or {},
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "last_notified_at": row.last_notified_at.isoformat() if row.last_notified_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


async def upsert_ci_incident(
    owner_id: str,
    failure: dict[str, Any],
) -> dict[str, Any]:
    owner = _owner(owner_id)
    external_id = _external_id(failure.get("external_id") or failure.get("cursor"))
    now = _utcnow()
    async with async_session_factory() as session:
        row = await session.scalar(
            select(CIIncident)
            .where(CIIncident.owner_id == owner, CIIncident.external_id == external_id)
            .with_for_update()
        )
        previous_streak = row.failure_streak if row is not None else 0
        if row is None:
            row = CIIncident(
                owner_id=owner,
                external_id=external_id,
                repository=_text(failure.get("repo"), 240) or "unknown/repository",
                workflow_name=_text(failure.get("workflow") or failure.get("name"), 200)
                or "workflow",
                branch=_text(failure.get("branch"), 160) or None,
                run_number=failure.get("run_number"),
                status=INCIDENT_OPEN,
                severity="medium",
                failure_streak=1,
                url=_text(failure.get("html_url"), 500) or None,
                evidence=incident_evidence(failure),
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(row)
        else:
            row.failure_streak = previous_streak + 1 if row.status != INCIDENT_RESOLVED else 1
            row.status = INCIDENT_OPEN
            row.resolved_at = None
            row.last_seen_at = now
            row.repository = _text(failure.get("repo"), 240) or row.repository
            row.workflow_name = (
                _text(failure.get("workflow") or failure.get("name"), 200) or row.workflow_name
            )
            row.branch = _text(failure.get("branch"), 160) or row.branch
            row.run_number = failure.get("run_number") or row.run_number
            row.url = _text(failure.get("html_url"), 500) or row.url
            row.evidence = incident_evidence(failure)
        severity = classify_ci_severity(
            failure,
            failure_streak=row.failure_streak,
            workflow_count=1,
        )
        if row is not None and SEVERITY_ORDER.get(row.severity, 99) < SEVERITY_ORDER[severity]:
            severity = row.severity
        row.severity = severity
        await session.commit()
        await session.refresh(row)
        return _incident_to_dict(row)


async def list_open_ci_incidents(
    owner_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    owner = _owner(owner_id)
    requested = _bounded_int(limit, 20, minimum=1, maximum=50)
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(CIIncident)
                .where(
                    CIIncident.owner_id == owner,
                    CIIncident.status.in_([INCIDENT_OPEN, INCIDENT_ACKNOWLEDGED]),
                )
                .order_by(CIIncident.last_seen_at.desc())
                .limit(requested)
            )
        ).all()
        return [_incident_to_dict(row) for row in rows]


async def mark_ci_incidents_notified(owner_id: str, external_ids: list[str]) -> None:
    owner = _owner(owner_id)
    ids = [_external_id(value) for value in external_ids if str(value or "").strip()]
    if not ids:
        return
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(CIIncident).where(
                    CIIncident.owner_id == owner,
                    CIIncident.external_id.in_(ids),
                )
            )
        ).all()
        now = _utcnow()
        for row in rows:
            row.last_notified_at = now
        await session.commit()


async def resolve_ci_incidents_after_complete_poll(
    owner_id: str,
    *,
    polled_repositories: list[str],
    seen_external_ids: list[str],
    complete: bool,
) -> int:
    """Resolve only after a complete, authenticated poll of those repositories."""

    if not complete or not polled_repositories:
        return 0
    owner = _owner(owner_id)
    repositories = [_text(value, 240) for value in polled_repositories if str(value or "").strip()]
    seen = [_external_id(value) for value in seen_external_ids if str(value or "").strip()]
    async with async_session_factory() as session:
        stmt = select(CIIncident).where(
            CIIncident.owner_id == owner,
            CIIncident.repository.in_(repositories),
            CIIncident.status.in_([INCIDENT_OPEN, INCIDENT_ACKNOWLEDGED]),
        )
        if seen:
            stmt = stmt.where(~CIIncident.external_id.in_(seen))
        rows = (await session.scalars(stmt)).all()
        now = _utcnow()
        for row in rows:
            row.status = INCIDENT_RESOLVED
            row.resolved_at = now
        await session.commit()
        return len(rows)
