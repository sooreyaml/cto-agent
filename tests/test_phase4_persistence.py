from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from src.brief.models import BriefRun
from src.brief.repository import create_brief_run, finish_brief_run
from src.ci.models import CIIncident
from src.ci.repository import (
    list_open_ci_incidents,
    resolve_ci_incidents_after_complete_poll,
    upsert_ci_incident,
)
from src.models import Base


@pytest.fixture
async def phase4_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[CIIncident.__table__, BriefRun.__table__],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("src.ci.repository.async_session_factory", factory)
    monkeypatch.setattr("src.brief.repository.async_session_factory", factory)
    yield factory
    await engine.dispose()


def _failure(external_id: str = "acme/api:42") -> dict:
    return {
        "external_id": external_id,
        "repo": "acme/api",
        "workflow": "CI",
        "branch": "main",
        "default_branch": "main",
        "run_number": 42,
        "html_url": "https://github.com/acme/api/actions/runs/42",
        "failed_jobs": [{"name": "test", "failed_steps": []}],
        "failure_signal": {"category": "Test or quality gate"},
    }


@pytest.mark.asyncio
async def test_ci_incident_streak_is_owner_scoped_and_partial_polls_do_not_resolve(
    phase4_db,
) -> None:
    first = await upsert_ci_incident("owner-1", _failure())
    repeated = await upsert_ci_incident("owner-1", _failure())
    other_owner = await upsert_ci_incident("owner-2", _failure())

    assert first["severity"] == "high"
    assert repeated["failure_streak"] == 2
    assert repeated["severity"] == "critical"
    assert other_owner["failure_streak"] == 1
    assert len(await list_open_ci_incidents("owner-1")) == 1

    assert (
        await resolve_ci_incidents_after_complete_poll(
            "owner-1",
            polled_repositories=["acme/api"],
            seen_external_ids=[],
            complete=False,
        )
        == 0
    )
    assert len(await list_open_ci_incidents("owner-1")) == 1

    assert (
        await resolve_ci_incidents_after_complete_poll(
            "owner-1",
            polled_repositories=["acme/api"],
            seen_external_ids=[],
            complete=True,
        )
        == 1
    )
    assert await list_open_ci_incidents("owner-1") == []


@pytest.mark.asyncio
async def test_brief_run_audits_render_and_delivery_status(phase4_db) -> None:
    created = await create_brief_run(
        "owner-1",
        run_date=datetime(2026, 9, 23),
        timezone="Europe/London",
        source_health={"github": {"ok": False}},
        signal_count="bad",
        action_count=2,
        evidence_urls=["https://github.com/acme/api/actions/runs/42"],
    )
    finished = await finish_brief_run(
        created["id"],
        render_status="fallback",
        delivery_status="sent",
        error_type="RuntimeError",
    )

    assert finished is not None
    assert finished["signal_count"] == 0
    assert finished["render_status"] == "fallback"
    assert finished["delivery_status"] == "sent"
    assert finished["delivered_at"] is not None

    async with phase4_db() as session:
        row = await session.scalar(select(BriefRun).where(BriefRun.id == UUID(created["id"])))
        assert row is not None
