from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from src.work.constants import (
    COMMITMENT_STATUSES,
    DUE_SOON_DAYS,
    KINDS,
    PRIORITY_STATUSES,
    SNAPSHOT_MAX_LINES,
    TASK_STATUSES,
)
from src.work.exceptions import InvalidWorkField, UnknownWorkKind
from src.work.models import Commitment, Decision, Priority, Reminder, Task


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def parse_kind(raw: object) -> str:
    kind = str(raw or "").strip()
    if kind not in KINDS:
        raise UnknownWorkKind(kind or "(empty)")
    return kind


def parse_uuid(raw: object, *, field: str) -> UUID:
    text = str(raw or "").strip()
    try:
        return UUID(text)
    except (ValueError, AttributeError, TypeError) as err:
        raise InvalidWorkField(f"Invalid {field}: {raw!r}") from err


def parse_optional_uuid(raw: object, *, field: str) -> UUID | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    return parse_uuid(text, field=field)


def parse_datetime(raw: object, *, field: str) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise InvalidWorkField(f"{field} is required")
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            parsed = datetime.fromisoformat(text)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as err:
        raise InvalidWorkField(f"Invalid {field}: {raw!r}") from err
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def parse_optional_datetime(raw: object, *, field: str) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    return parse_datetime(text, field=field)


def parse_status(raw: object, allowed: frozenset[str], *, field: str = "status") -> str:
    status = str(raw or "").strip()
    if status not in allowed:
        raise InvalidWorkField(f"Invalid {field}: {raw!r}")
    return status


def parse_optional_status(
    raw: object, allowed: frozenset[str], *, field: str = "status"
) -> str | None:
    if raw is None or str(raw).strip() == "":
        return None
    return parse_status(raw, allowed, field=field)


def parse_rank(raw: object) -> int:
    try:
        rank = int(raw)
    except (TypeError, ValueError) as err:
        raise InvalidWorkField(f"Invalid rank: {raw!r}") from err
    if rank < 1:
        raise InvalidWorkField("rank must be >= 1")
    return rank


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def priority_to_dict(row: Priority) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "priority",
        "title": row.title,
        "rank": row.rank,
        "status": row.status,
        "notes": row.notes,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def task_to_dict(row: Task) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "task",
        "title": row.title,
        "status": row.status,
        "due_at": iso(row.due_at),
        "project": row.project,
        "blocked_reason": row.blocked_reason,
        "notes": row.notes,
        "priority_id": str(row.priority_id) if row.priority_id else None,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def decision_to_dict(row: Decision) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "decision",
        "title": row.title,
        "decision": row.decision,
        "rationale": row.rationale,
        "decided_at": iso(row.decided_at),
        "related_task_id": str(row.related_task_id) if row.related_task_id else None,
        "created_at": iso(row.created_at),
    }


def commitment_to_dict(row: Commitment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "commitment",
        "who": row.who,
        "what": row.what,
        "due_at": iso(row.due_at),
        "source": row.source,
        "status": row.status,
        "remind_at": iso(row.remind_at),
        "last_reminded_at": iso(row.last_reminded_at),
        "related_task_id": str(row.related_task_id) if row.related_task_id else None,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def reminder_to_dict(row: Reminder) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "message": row.message,
        "fire_at": iso(row.fire_at),
        "sent_at": iso(row.sent_at),
        "commitment_id": str(row.commitment_id) if row.commitment_id else None,
        "created_at": iso(row.created_at),
    }


def due_soon_cutoff(now: datetime | None = None) -> datetime:
    current = now or utcnow()
    return current + timedelta(days=DUE_SOON_DAYS)


def task_is_snapshot_worthy(task: dict[str, Any], *, now: datetime, cutoff: datetime) -> bool:
    if task.get("status") == "blocked":
        return True
    if task.get("status") != "open":
        return False
    due = task.get("due_at")
    if not due:
        return False
    parsed = datetime.fromisoformat(due)
    return parsed <= cutoff


def format_work_snapshot(
    *,
    priorities: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    commitments: list[dict[str, Any]],
    now: datetime | None = None,
) -> str:
    current = now or utcnow()
    cutoff = due_soon_cutoff(current)
    lines: list[str] = ["Work board (authoritative; mutate with work_create / work_update):"]

    open_priorities = sorted(
        [p for p in priorities if p.get("status") == "open"],
        key=lambda p: (p.get("rank") or 99, p.get("title") or ""),
    )
    if open_priorities:
        lines.append("Priorities:")
        for item in open_priorities:
            extra = f" — {item['notes']}" if item.get("notes") else ""
            lines.append(f"- P{item.get('rank')}: {item.get('title')}{extra}")
    else:
        lines.append("Priorities: (none)")

    snap_tasks = [t for t in tasks if task_is_snapshot_worthy(t, now=current, cutoff=cutoff)]
    snap_tasks.sort(
        key=lambda t: (
            0 if t.get("status") == "blocked" else 1,
            t.get("due_at") or "9999",
            t.get("title") or "",
        )
    )
    if snap_tasks:
        lines.append("Tasks (blocked / due soon):")
        for item in snap_tasks:
            due = f" due {item['due_at'][:10]}" if item.get("due_at") else ""
            blocked = f" blocked: {item['blocked_reason']}" if item.get("blocked_reason") else ""
            project = f" [{item['project']}]" if item.get("project") else ""
            lines.append(f"- {item.get('title')} ({item.get('status')}){project}{due}{blocked}")

    open_commitments = [c for c in commitments if c.get("status") == "open"]
    open_commitments.sort(key=lambda c: (c.get("due_at") or "9999", c.get("what") or ""))
    if open_commitments:
        lines.append("Commitments:")
        for item in open_commitments:
            due = f" by {item['due_at'][:10]}" if item.get("due_at") else ""
            lines.append(f"- {item.get('who')}: {item.get('what')}{due}")

    if len(lines) == 1:
        lines.append("(empty)")
    return "\n".join(lines[:SNAPSHOT_MAX_LINES])


def statuses_for_kind(kind: str) -> frozenset[str] | None:
    if kind == "priority":
        return PRIORITY_STATUSES
    if kind == "task":
        return TASK_STATUSES
    if kind == "commitment":
        return COMMITMENT_STATUSES
    return None
