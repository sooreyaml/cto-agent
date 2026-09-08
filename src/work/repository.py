from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory
from src.work.constants import (
    COMMITMENT_STATUSES,
    LIST_DEFAULT_LIMIT,
    LIST_MAX_LIMIT,
    MAX_OPEN_PRIORITIES,
    PRIORITY_STATUSES,
    TASK_STATUSES,
)
from src.work.exceptions import InvalidWorkField, OpenPriorityLimit, WorkNotFound
from src.work.mapping import (
    commitment_to_dict,
    decision_to_dict,
    parse_datetime,
    parse_kind,
    parse_optional_datetime,
    parse_optional_status,
    parse_optional_uuid,
    parse_rank,
    parse_status,
    parse_uuid,
    priority_to_dict,
    reminder_to_dict,
    statuses_for_kind,
    task_to_dict,
    utcnow,
)
from src.work.models import Commitment, Decision, Priority, Reminder, Task, WatchCursor


def _limit(raw: object) -> int:
    try:
        return min(max(int(raw or LIST_DEFAULT_LIMIT), 1), LIST_MAX_LIMIT)
    except (TypeError, ValueError):
        return LIST_DEFAULT_LIMIT


def _text(raw: object) -> str:
    return str(raw or "").strip()


def _optional_text(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


async def _open_priority_count(session: AsyncSession, *, exclude_id: UUID | None = None) -> int:
    stmt = select(func.count()).select_from(Priority).where(Priority.status == "open")
    if exclude_id is not None:
        stmt = stmt.where(Priority.id != exclude_id)
    return int(await session.scalar(stmt) or 0)


async def _next_rank(session: AsyncSession) -> int:
    current = await session.scalar(select(func.max(Priority.rank)))
    return (current or 0) + 1


async def _create_priority(session: AsyncSession, fields: dict[str, Any]) -> Priority:
    title = _text(fields.get("title"))
    if not title:
        raise InvalidWorkField("title is required")
    status = parse_optional_status(fields.get("status"), PRIORITY_STATUSES) or "open"
    if status == "open" and await _open_priority_count(session) >= MAX_OPEN_PRIORITIES:
        raise OpenPriorityLimit(MAX_OPEN_PRIORITIES)
    rank = (
        parse_rank(fields["rank"]) if fields.get("rank") is not None else await _next_rank(session)
    )
    now = utcnow()
    row = Priority(
        title=title,
        rank=rank,
        status=status,
        notes=_optional_text(fields.get("notes")),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _create_task(session: AsyncSession, fields: dict[str, Any]) -> Task:
    title = _text(fields.get("title"))
    if not title:
        raise InvalidWorkField("title is required")
    now = utcnow()
    row = Task(
        title=title,
        status=parse_optional_status(fields.get("status"), TASK_STATUSES) or "open",
        due_at=parse_optional_datetime(fields.get("due_at"), field="due_at"),
        project=_optional_text(fields.get("project")),
        blocked_reason=_optional_text(fields.get("blocked_reason")),
        notes=_optional_text(fields.get("notes")),
        priority_id=parse_optional_uuid(fields.get("priority_id"), field="priority_id"),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _create_decision(session: AsyncSession, fields: dict[str, Any]) -> Decision:
    title = _text(fields.get("title"))
    decision = _text(fields.get("decision"))
    if not title or not decision:
        raise InvalidWorkField("title and decision are required")
    row = Decision(
        title=title,
        decision=decision,
        rationale=_optional_text(fields.get("rationale")),
        decided_at=parse_optional_datetime(fields.get("decided_at"), field="decided_at")
        or utcnow(),
        related_task_id=parse_optional_uuid(fields.get("related_task_id"), field="related_task_id"),
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def _create_commitment(session: AsyncSession, fields: dict[str, Any]) -> Commitment:
    what = _text(fields.get("what"))
    if not what:
        raise InvalidWorkField("what is required")
    now = utcnow()
    row = Commitment(
        who=_text(fields.get("who")) or "me",
        what=what,
        due_at=parse_optional_datetime(fields.get("due_at"), field="due_at"),
        source=_optional_text(fields.get("source")),
        status=parse_optional_status(fields.get("status"), COMMITMENT_STATUSES) or "open",
        remind_at=parse_optional_datetime(fields.get("remind_at"), field="remind_at"),
        related_task_id=parse_optional_uuid(fields.get("related_task_id"), field="related_task_id"),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


def _apply_clearable(row: Any, field: str, raw: object, *, parse=None) -> None:
    if raw is None:
        return
    if isinstance(raw, str) and raw.strip() == "":
        setattr(row, field, None)
        return
    setattr(row, field, parse(raw) if parse else _text(raw))


async def _update_priority(
    session: AsyncSession, item_id: UUID, fields: dict[str, Any]
) -> Priority:
    row = await session.get(Priority, item_id)
    if row is None:
        raise WorkNotFound("priority", str(item_id))
    if fields.get("title") is not None:
        title = _text(fields.get("title"))
        if not title:
            raise InvalidWorkField("title cannot be empty")
        row.title = title
    if fields.get("rank") is not None:
        row.rank = parse_rank(fields.get("rank"))
    if fields.get("status") is not None:
        status = parse_status(fields.get("status"), PRIORITY_STATUSES)
        if (
            status == "open"
            and row.status != "open"
            and await _open_priority_count(session, exclude_id=row.id) >= MAX_OPEN_PRIORITIES
        ):
            raise OpenPriorityLimit(MAX_OPEN_PRIORITIES)
        row.status = status
    if "notes" in fields:
        _apply_clearable(row, "notes", fields.get("notes"))
    row.updated_at = utcnow()
    await session.flush()
    return row


async def _update_task(session: AsyncSession, item_id: UUID, fields: dict[str, Any]) -> Task:
    row = await session.get(Task, item_id)
    if row is None:
        raise WorkNotFound("task", str(item_id))
    if fields.get("title") is not None:
        title = _text(fields.get("title"))
        if not title:
            raise InvalidWorkField("title cannot be empty")
        row.title = title
    if fields.get("status") is not None:
        row.status = parse_status(fields.get("status"), TASK_STATUSES)
    if "due_at" in fields:
        _apply_clearable(
            row,
            "due_at",
            fields.get("due_at"),
            parse=lambda v: parse_datetime(v, field="due_at"),
        )
    if "project" in fields:
        _apply_clearable(row, "project", fields.get("project"))
    if "blocked_reason" in fields:
        _apply_clearable(row, "blocked_reason", fields.get("blocked_reason"))
    if "notes" in fields:
        _apply_clearable(row, "notes", fields.get("notes"))
    if "priority_id" in fields:
        _apply_clearable(
            row,
            "priority_id",
            fields.get("priority_id"),
            parse=lambda v: parse_uuid(v, field="priority_id"),
        )
    row.updated_at = utcnow()
    await session.flush()
    return row


async def _update_decision(
    session: AsyncSession, item_id: UUID, fields: dict[str, Any]
) -> Decision:
    row = await session.get(Decision, item_id)
    if row is None:
        raise WorkNotFound("decision", str(item_id))
    if fields.get("title") is not None:
        title = _text(fields.get("title"))
        if not title:
            raise InvalidWorkField("title cannot be empty")
        row.title = title
    if fields.get("decision") is not None:
        decision = _text(fields.get("decision"))
        if not decision:
            raise InvalidWorkField("decision cannot be empty")
        row.decision = decision
    if "rationale" in fields:
        _apply_clearable(row, "rationale", fields.get("rationale"))
    if fields.get("decided_at") is not None and str(fields.get("decided_at")).strip() != "":
        row.decided_at = parse_datetime(fields.get("decided_at"), field="decided_at")
    if "related_task_id" in fields:
        _apply_clearable(
            row,
            "related_task_id",
            fields.get("related_task_id"),
            parse=lambda v: parse_uuid(v, field="related_task_id"),
        )
    await session.flush()
    return row


async def _update_commitment(
    session: AsyncSession, item_id: UUID, fields: dict[str, Any]
) -> Commitment:
    row = await session.get(Commitment, item_id)
    if row is None:
        raise WorkNotFound("commitment", str(item_id))
    if fields.get("who") is not None:
        row.who = _text(fields.get("who")) or "me"
    if fields.get("what") is not None:
        what = _text(fields.get("what"))
        if not what:
            raise InvalidWorkField("what cannot be empty")
        row.what = what
    if fields.get("status") is not None:
        row.status = parse_status(fields.get("status"), COMMITMENT_STATUSES)
    if "due_at" in fields:
        _apply_clearable(
            row, "due_at", fields.get("due_at"), parse=lambda v: parse_datetime(v, field="due_at")
        )
    if "source" in fields:
        _apply_clearable(row, "source", fields.get("source"))
    if "remind_at" in fields:
        _apply_clearable(
            row,
            "remind_at",
            fields.get("remind_at"),
            parse=lambda v: parse_datetime(v, field="remind_at"),
        )
    if "related_task_id" in fields:
        _apply_clearable(
            row,
            "related_task_id",
            fields.get("related_task_id"),
            parse=lambda v: parse_uuid(v, field="related_task_id"),
        )
    row.updated_at = utcnow()
    await session.flush()
    return row


async def _list_priorities(
    session: AsyncSession, *, status: str | None, query: str | None, limit: int
) -> list[dict[str, Any]]:
    stmt = select(Priority).order_by(Priority.rank.asc(), Priority.created_at.desc())
    if status:
        stmt = stmt.where(Priority.status == status)
    if query:
        pattern = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Priority.title).like(pattern), func.lower(Priority.notes).like(pattern))
        )
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [priority_to_dict(row) for row in rows]


async def _list_tasks(
    session: AsyncSession,
    *,
    status: str | None,
    query: str | None,
    due_before: Any,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = select(Task).order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
    if status:
        stmt = stmt.where(Task.status == status)
    if query:
        pattern = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Task.title).like(pattern),
                func.lower(Task.project).like(pattern),
                func.lower(Task.notes).like(pattern),
            )
        )
    if due_before is not None:
        stmt = stmt.where(Task.due_at.is_not(None), Task.due_at <= due_before)
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [task_to_dict(row) for row in rows]


async def _list_decisions(
    session: AsyncSession, *, query: str | None, limit: int
) -> list[dict[str, Any]]:
    stmt = select(Decision).order_by(Decision.decided_at.desc(), Decision.created_at.desc())
    if query:
        pattern = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Decision.title).like(pattern),
                func.lower(Decision.decision).like(pattern),
                func.lower(Decision.rationale).like(pattern),
            )
        )
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [decision_to_dict(row) for row in rows]


async def _list_commitments(
    session: AsyncSession,
    *,
    status: str | None,
    query: str | None,
    due_before: Any,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = select(Commitment).order_by(
        Commitment.due_at.asc().nullslast(), Commitment.created_at.desc()
    )
    if status:
        stmt = stmt.where(Commitment.status == status)
    if query:
        pattern = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Commitment.what).like(pattern),
                func.lower(Commitment.who).like(pattern),
                func.lower(Commitment.source).like(pattern),
            )
        )
    if due_before is not None:
        stmt = stmt.where(Commitment.due_at.is_not(None), Commitment.due_at <= due_before)
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [commitment_to_dict(row) for row in rows]


async def list_work(args: dict[str, Any]) -> list[dict[str, Any]]:
    kind = parse_kind(args.get("kind"))
    allowed = statuses_for_kind(kind)
    status = parse_optional_status(args.get("status"), allowed) if allowed else None
    query = _optional_text(args.get("query"))
    due_before = parse_optional_datetime(args.get("due_before"), field="due_before")
    limit = _limit(args.get("limit"))
    async with async_session_factory() as session:
        if kind == "priority":
            rows = await _list_priorities(session, status=status, query=query, limit=limit)
        elif kind == "task":
            rows = await _list_tasks(
                session, status=status, query=query, due_before=due_before, limit=limit
            )
        elif kind == "decision":
            rows = await _list_decisions(session, query=query, limit=limit)
        else:
            rows = await _list_commitments(
                session, status=status, query=query, due_before=due_before, limit=limit
            )
        return rows


async def create_work(args: dict[str, Any]) -> dict[str, Any]:
    kind = parse_kind(args.get("kind"))
    async with async_session_factory() as session:
        if kind == "priority":
            row = await _create_priority(session, args)
            payload = priority_to_dict(row)
        elif kind == "task":
            row = await _create_task(session, args)
            payload = task_to_dict(row)
        elif kind == "decision":
            row = await _create_decision(session, args)
            payload = decision_to_dict(row)
        else:
            row = await _create_commitment(session, args)
            payload = commitment_to_dict(row)
        await session.commit()
        return payload


async def update_work(args: dict[str, Any]) -> dict[str, Any]:
    kind = parse_kind(args.get("kind"))
    item_id = parse_uuid(args.get("id"), field="id")
    async with async_session_factory() as session:
        if kind == "priority":
            row = await _update_priority(session, item_id, args)
            payload = priority_to_dict(row)
        elif kind == "task":
            row = await _update_task(session, item_id, args)
            payload = task_to_dict(row)
        elif kind == "decision":
            row = await _update_decision(session, item_id, args)
            payload = decision_to_dict(row)
        else:
            row = await _update_commitment(session, item_id, args)
            payload = commitment_to_dict(row)
        await session.commit()
        return payload


async def snapshot_rows() -> dict[str, list[dict[str, Any]]]:
    async with async_session_factory() as session:
        priorities = await _list_priorities(
            session, status="open", query=None, limit=MAX_OPEN_PRIORITIES
        )
        tasks = await _list_tasks(session, status=None, query=None, due_before=None, limit=40)
        commitments = await _list_commitments(
            session, status="open", query=None, due_before=None, limit=20
        )
        return {"priorities": priorities, "tasks": tasks, "commitments": commitments}


async def brief_bundle() -> dict[str, Any]:
    async with async_session_factory() as session:
        priorities = await _list_priorities(
            session, status="open", query=None, limit=MAX_OPEN_PRIORITIES
        )
        tasks = await _list_tasks(session, status=None, query=None, due_before=None, limit=40)
        commitments = await _list_commitments(
            session, status="open", query=None, due_before=None, limit=30
        )
        decisions = await _list_decisions(session, query=None, limit=5)
        open_tasks = [t for t in tasks if t["status"] in {"open", "blocked"}]
        return {
            "priorities": priorities,
            "tasks": open_tasks,
            "commitments": commitments,
            "recent_decisions": decisions,
        }


async def create_reminder(args: dict[str, Any]) -> dict[str, Any]:
    message = _text(args.get("message"))
    if not message:
        raise InvalidWorkField("message is required")
    fire_at = parse_datetime(args.get("fire_at"), field="fire_at")
    async with async_session_factory() as session:
        row = Reminder(
            message=message,
            fire_at=fire_at,
            commitment_id=parse_optional_uuid(args.get("commitment_id"), field="commitment_id"),
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        payload = reminder_to_dict(row)
        await session.commit()
        return payload


async def cancel_reminder(args: dict[str, Any]) -> dict[str, Any]:
    item_id = parse_uuid(args.get("id"), field="id")
    async with async_session_factory() as session:
        row = await session.get(Reminder, item_id)
        if row is None:
            raise WorkNotFound("reminder", str(item_id))
        if row.sent_at is not None:
            raise InvalidWorkField("reminder already sent")
        await session.delete(row)
        await session.commit()
        return {"id": str(item_id), "cancelled": True}


async def due_items(now: datetime | None = None) -> dict[str, list[dict[str, Any]]]:
    current = now or utcnow()
    async with async_session_factory() as session:
        reminders = (
            (
                await session.execute(
                    select(Reminder)
                    .where(Reminder.sent_at.is_(None), Reminder.fire_at <= current)
                    .order_by(Reminder.fire_at.asc())
                )
            )
            .scalars()
            .all()
        )
        commitments = (
            (
                await session.execute(
                    select(Commitment).where(
                        Commitment.status == "open",
                        Commitment.remind_at.is_not(None),
                        Commitment.remind_at <= current,
                        or_(
                            Commitment.last_reminded_at.is_(None),
                            Commitment.last_reminded_at < Commitment.remind_at,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            "reminders": [reminder_to_dict(row) for row in reminders],
            "commitments": [commitment_to_dict(row) for row in commitments],
        }


async def mark_reminders_sent(
    reminder_ids: list[str], commitment_ids: list[str], *, now: datetime | None = None
) -> None:
    current = now or utcnow()
    async with async_session_factory() as session:
        for raw in reminder_ids:
            row = await session.get(Reminder, parse_uuid(raw, field="id"))
            if row is not None:
                row.sent_at = current
        for raw in commitment_ids:
            row = await session.get(Commitment, parse_uuid(raw, field="id"))
            if row is not None:
                row.last_reminded_at = current
                row.updated_at = current
        await session.commit()


async def unseen_watch_ids(source: str, external_ids: list[str]) -> set[str]:
    if not external_ids:
        return set()
    async with async_session_factory() as session:
        existing = (
            (
                await session.execute(
                    select(WatchCursor.external_id).where(
                        WatchCursor.source == source,
                        WatchCursor.external_id.in_(external_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return set(external_ids) - set(existing)


async def record_watch_cursors(source: str, external_ids: list[str]) -> None:
    if not external_ids:
        return
    now = utcnow()
    async with async_session_factory() as session:
        for external_id in external_ids:
            session.add(WatchCursor(source=source, external_id=external_id, notified_at=now))
        await session.commit()
