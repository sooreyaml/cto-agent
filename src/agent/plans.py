"""Persistence for the Phase 3 plan/execute/verify controller."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.agent.planning import PlanDraft, plan_evidence_from_outcome
from src.connections.redact import redact_secrets
from src.database import async_session_factory
from src.memory.models import AgentPlan

PLAN_STATUSES = frozenset({"planned", "executing", "verifying", "completed", "blocked", "failed"})
TERMINAL_PLAN_STATUSES = frozenset({"completed", "blocked", "failed"})
_PLAN_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"planned", "executing", "blocked", "failed"}),
    "executing": frozenset({"executing", "verifying", "blocked", "failed"}),
    "verifying": frozenset({"verifying", "completed", "blocked", "failed"}),
    "completed": frozenset({"completed"}),
    "blocked": frozenset({"blocked"}),
    "failed": frozenset({"failed"}),
}
MAX_PLAN_EVIDENCE = 50
MAX_PLAN_SUMMARY_CHARS = 600


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _bounded_text(value: object, max_chars: int) -> str:
    text = redact_secrets(str(value or "").strip())
    return text[:max_chars]


def _plan_id(value: object) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("plan_id must be a UUID") from exc


def _owner_id(value: object) -> str:
    owner = _bounded_text(value, 120)
    if not owner:
        raise ValueError("owner_id is required")
    return owner


def _channel_id(value: object) -> str:
    channel = _bounded_text(value, 200)
    if not channel:
        raise ValueError("channel_id is required")
    return channel


def _status(value: object) -> str:
    status = str(value or "").strip().lower()
    if status not in PLAN_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(PLAN_STATUSES))}")
    return status


def _steps(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("steps must be a list")
    clean: list[dict[str, Any]] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        clean.append(
            {
                "id": _bounded_text(item.get("id"), 80),
                "title": _bounded_text(item.get("title"), 240),
                "status": _bounded_text(item.get("status"), 40),
            }
        )
    return clean


def _evidence(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    clean: list[dict[str, Any]] = []
    for item in value[-MAX_PLAN_EVIDENCE:]:
        if not isinstance(item, dict):
            continue
        clean.append(plan_evidence_from_outcome(item))
    return clean


def plan_to_dict(row: AgentPlan) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "trace_id": row.trace_id,
        "owner_id": row.owner_id,
        "channel_id": row.channel_id,
        "objective": row.objective,
        "constraints": list(row.constraints or []),
        "acceptance_criteria": list(row.acceptance_criteria or []),
        "steps": list(row.steps or []),
        "evidence": list(row.evidence or []),
        "status": row.status,
        "verification_summary": row.verification_summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


async def create_agent_plan(
    owner_id: str,
    *,
    channel_id: str,
    trace_id: str,
    draft: PlanDraft,
) -> dict[str, Any]:
    now = _utcnow()
    row = AgentPlan(
        owner_id=_owner_id(owner_id),
        channel_id=_channel_id(channel_id),
        trace_id=_bounded_text(trace_id, 120),
        objective=_bounded_text(draft.objective, 1_200),
        constraints=list(draft.constraints),
        acceptance_criteria=list(draft.acceptance_criteria),
        steps=_steps([dict(step) for step in draft.steps]),
        evidence=[],
        status="planned",
        created_at=now,
        updated_at=now,
    )
    async with async_session_factory() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return plan_to_dict(row)


async def update_agent_plan(
    plan_id: str,
    owner_id: str,
    *,
    channel_id: str | None = None,
    status: str,
    steps: list[dict[str, Any]] | None = None,
    verification_summary: str | None = None,
) -> dict[str, Any] | None:
    normalized_status = _status(status)
    owner = _owner_id(owner_id)
    channel = _channel_id(channel_id) if channel_id is not None else None
    now = _utcnow()
    async with async_session_factory() as session:
        filters = [AgentPlan.id == _plan_id(plan_id), AgentPlan.owner_id == owner]
        if channel is not None:
            filters.append(AgentPlan.channel_id == channel)
        row = await session.scalar(select(AgentPlan).where(*filters).with_for_update())
        if row is None:
            return None
        if normalized_status not in _PLAN_TRANSITIONS.get(row.status, frozenset()):
            raise ValueError(f"invalid plan transition: {row.status} -> {normalized_status}")
        row.status = normalized_status
        row.updated_at = now
        if steps is not None:
            row.steps = _steps(steps)
        if verification_summary is not None:
            row.verification_summary = _bounded_text(verification_summary, MAX_PLAN_SUMMARY_CHARS)
        if normalized_status in TERMINAL_PLAN_STATUSES and row.completed_at is None:
            row.completed_at = now
        await session.commit()
        await session.refresh(row)
        return plan_to_dict(row)


async def append_agent_plan_evidence(
    plan_id: str,
    owner_id: str,
    outcome: dict[str, Any],
    *,
    channel_id: str | None = None,
) -> dict[str, Any] | None:
    owner = _owner_id(owner_id)
    channel = _channel_id(channel_id) if channel_id is not None else None
    evidence = plan_evidence_from_outcome(outcome)
    async with async_session_factory() as session:
        filters = [AgentPlan.id == _plan_id(plan_id), AgentPlan.owner_id == owner]
        if channel is not None:
            filters.append(AgentPlan.channel_id == channel)
        row = await session.scalar(select(AgentPlan).where(*filters).with_for_update())
        if row is None:
            return None
        existing = _evidence(row.evidence)
        row.evidence = [*existing, evidence][-MAX_PLAN_EVIDENCE:]
        row.updated_at = _utcnow()
        await session.commit()
        await session.refresh(row)
        return plan_to_dict(row)
