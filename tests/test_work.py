from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from src.models import Base
from src.work.exceptions import OpenPriorityLimit, WorkNotFound
from src.work.mapping import (
    format_work_snapshot,
    parse_datetime,
    parse_kind,
    parse_optional_datetime,
    task_is_snapshot_worthy,
)
from src.work.models import Commitment, Decision, Priority, Reminder, Task, WatchCursor
from src.work.repository import (
    create_reminder,
    create_work,
    due_items,
    list_work,
    mark_reminders_sent,
    record_watch_cursors,
    unseen_watch_ids,
    update_work,
)


def test_parse_kind_rejects_unknown() -> None:
    with pytest.raises(Exception, match="Unknown work kind"):
        parse_kind("epic")


def test_parse_datetime_date_and_z() -> None:
    assert parse_datetime("2026-09-10", field="due_at") == datetime(2026, 9, 10)
    zulu = parse_datetime("2026-09-10T12:00:00Z", field="due_at")
    assert zulu == datetime(2026, 9, 10, 12, 0, 0)
    assert zulu.tzinfo is None


def test_parse_optional_datetime_empty_clears() -> None:
    assert parse_optional_datetime("", field="due_at") is None
    assert parse_optional_datetime(None, field="due_at") is None


def test_task_snapshot_includes_blocked_and_due() -> None:
    now = datetime(2026, 9, 8, 12, 0, 0)
    cutoff = datetime(2026, 9, 15)
    assert task_is_snapshot_worthy({"status": "blocked", "due_at": None}, now=now, cutoff=cutoff)
    assert task_is_snapshot_worthy(
        {"status": "open", "due_at": "2026-09-09T00:00:00"}, now=now, cutoff=cutoff
    )
    assert not task_is_snapshot_worthy(
        {"status": "open", "due_at": "2026-10-01T00:00:00"}, now=now, cutoff=cutoff
    )
    assert not task_is_snapshot_worthy(
        {"status": "done", "due_at": "2026-09-01T00:00:00"}, now=now, cutoff=cutoff
    )


def test_format_work_snapshot_caps_and_orders() -> None:
    text = format_work_snapshot(
        priorities=[
            {"title": "Ship agent", "rank": 1, "status": "open", "notes": "phase 1"},
            {"title": "Dropped", "rank": 2, "status": "done"},
        ],
        tasks=[
            {
                "title": "Blocked deploy",
                "status": "blocked",
                "blocked_reason": "secrets",
                "project": "cto-agent",
                "due_at": None,
            },
            {
                "title": "Later",
                "status": "open",
                "due_at": "2026-12-01T00:00:00",
            },
        ],
        commitments=[
            {
                "who": "me",
                "what": "Email investor",
                "due_at": "2026-09-09T00:00:00",
                "status": "open",
            }
        ],
        now=datetime(2026, 9, 8, 12, 0, 0),
    )
    assert "P1: Ship agent" in text
    assert "Dropped" not in text
    assert "Blocked deploy" in text
    assert "Later" not in text
    assert "Email investor" in text
    assert "Notion" not in text
    assert len(text.splitlines()) <= 15


@pytest.fixture
async def work_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Priority.__table__,
        Task.__table__,
        Decision.__table__,
        Commitment.__table__,
        Reminder.__table__,
        WatchCursor.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("src.work.repository.async_session_factory", factory)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_priority_cap_and_list_filter(work_db) -> None:
    for index in range(5):
        await create_work({"kind": "priority", "title": f"P{index + 1}", "rank": index + 1})
    with pytest.raises(OpenPriorityLimit):
        await create_work({"kind": "priority", "title": "P6"})
    rows = await list_work({"kind": "priority", "status": "open"})
    assert len(rows) == 5
    first = rows[0]
    await update_work({"kind": "priority", "id": first["id"], "status": "done"})
    sixth = await create_work({"kind": "priority", "title": "P6", "rank": 6})
    assert sixth["title"] == "P6"
    remaining = await list_work({"kind": "priority", "status": "open"})
    assert len(remaining) == 5


@pytest.mark.asyncio
async def test_task_query_and_clear_due(work_db) -> None:
    created = await create_work(
        {
            "kind": "task",
            "title": "Fix CI",
            "project": "cto-agent",
            "due_at": "2026-09-10",
            "status": "open",
        }
    )
    found = await list_work({"kind": "task", "query": "ci", "status": "open"})
    assert [row["id"] for row in found] == [created["id"]]
    due_filtered = await list_work({"kind": "task", "due_before": "2026-09-11"})
    assert len(due_filtered) == 1
    updated = await update_work({"kind": "task", "id": created["id"], "due_at": ""})
    assert updated["due_at"] is None


@pytest.mark.asyncio
async def test_decision_and_commitment_roundtrip(work_db) -> None:
    decision = await create_work(
        {"kind": "decision", "title": "Host", "decision": "Stay on Coolify", "rationale": "simpler"}
    )
    assert decision["decision"] == "Stay on Coolify"
    commitment = await create_work(
        {"kind": "commitment", "who": "me", "what": "Write brief", "due_at": "2026-09-12"}
    )
    listed = await list_work({"kind": "commitment", "query": "brief"})
    assert listed[0]["id"] == commitment["id"]
    with pytest.raises(WorkNotFound):
        await update_work({"kind": "task", "id": commitment["id"], "title": "nope"})


@pytest.mark.asyncio
async def test_due_reminders_and_commitment_nudge(work_db) -> None:
    reminder = await create_reminder({"message": "Standup notes", "fire_at": "2020-01-01T00:00:00"})
    commitment = await create_work(
        {
            "kind": "commitment",
            "what": "Follow up",
            "remind_at": "2020-01-01T00:00:00",
        }
    )
    bundle = await due_items(now=datetime(2026, 9, 8, 12, 0, 0))
    assert [item["id"] for item in bundle["reminders"]] == [reminder["id"]]
    assert [item["id"] for item in bundle["commitments"]] == [commitment["id"]]
    await mark_reminders_sent(
        [reminder["id"]], [commitment["id"]], now=datetime(2026, 9, 8, 12, 0, 0)
    )
    again = await due_items(now=datetime(2026, 9, 8, 13, 0, 0))
    assert again["reminders"] == []
    assert again["commitments"] == []


@pytest.mark.asyncio
async def test_watch_cursors_dedupe(work_db) -> None:
    unseen = await unseen_watch_ids("github_actions", ["acme/api:1", "acme/api:2"])
    assert unseen == {"acme/api:1", "acme/api:2"}
    await record_watch_cursors("github_actions", ["acme/api:1"])
    unseen = await unseen_watch_ids("github_actions", ["acme/api:1", "acme/api:2"])
    assert unseen == {"acme/api:2"}
