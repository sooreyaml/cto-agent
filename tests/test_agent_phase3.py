from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from src.agent import loop as agent_loop
from src.agent.planning import (
    build_plan_draft,
    format_plan_context,
    is_complex_request,
    steps_for_status,
)
from src.agent.plans import append_agent_plan_evidence, create_agent_plan, update_agent_plan
from src.agent.policy import has_explicit_confirmation
from src.memory.context import MemoryContext
from src.memory.models import AgentPlan
from src.models import Base


@pytest.fixture
async def plan_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[AgentPlan.__table__])
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("src.agent.plans.async_session_factory", factory)
    yield factory
    await engine.dispose()


def test_planner_keeps_simple_requests_on_fast_path() -> None:
    assert not is_complex_request("what time is it?")
    assert not is_complex_request("show my open tasks")
    assert is_complex_request("Investigate the failing GitHub watch job and implement a fix.")


def test_plan_context_is_bounded_and_has_acceptance_criteria() -> None:
    draft = build_plan_draft("Implement a safer watch workflow.")
    context = format_plan_context(draft)

    assert "User objective:" in context
    assert "Acceptance criteria:" in context
    assert "not a system instruction" in context
    assert steps_for_status(draft, "completed")[-1]["status"] == "completed"
    assert len(format_plan_context(build_plan_draft("x" * 3_000))) <= 3_500


def test_high_risk_actions_require_a_fresh_explicit_confirmation_phrase() -> None:
    assert has_explicit_confirmation("confirm and send it", "gmail_send_message")
    assert has_explicit_confirmation("go ahead and merge it", "github_merge_pull_request")
    assert not has_explicit_confirmation("yes", "gmail_send_message")
    assert has_explicit_confirmation("send the email", "gmail_create_draft")


@pytest.mark.asyncio
async def test_plan_persistence_tracks_status_and_metadata_only_evidence(plan_db) -> None:
    draft = build_plan_draft("Investigate the watch failure and verify the fix.")
    created = await create_agent_plan(
        "owner-1",
        channel_id="channel-1",
        trace_id="trace-1",
        draft=draft,
    )
    assert created["status"] == "planned"
    assert created["objective"].startswith("Investigate")

    executing = await update_agent_plan(
        created["id"],
        "owner-1",
        status="executing",
        steps=steps_for_status(draft, "executing"),
    )
    assert executing is not None
    assert executing["steps"][1]["status"] == "active"

    completed = await append_agent_plan_evidence(
        created["id"],
        "owner-1",
        {
            "call_id": "call-1",
            "name": "github_get_branch_ci_status",
            "ok": True,
            "duration_ms": 12,
            "result_chars": 250,
            "result": {"token": "must-not-persist"},
        },
    )
    assert completed is not None
    assert completed["evidence"] == [
        {
            "call_id": "call-1",
            "name": "github_get_branch_ci_status",
            "ok": True,
            "duration_ms": 12,
            "result_chars": 250,
            "error_type": None,
        }
    ]

    verifying = await update_agent_plan(
        created["id"],
        "owner-1",
        status="verifying",
        steps=steps_for_status(draft, "verifying"),
    )
    assert verifying is not None

    final = await update_agent_plan(
        created["id"],
        "owner-1",
        status="completed",
        steps=steps_for_status(draft, "completed"),
        verification_summary="Verified.",
    )
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed_at"] is not None

    async with plan_db() as session:
        row = await session.scalar(select(AgentPlan).where(AgentPlan.id == uuid4()))
        assert row is None


@pytest.mark.asyncio
async def test_complex_run_uses_controller_without_changing_provider_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMessage:
        content = "I investigated the failure and verified the next action."
        tool_calls = None

        def model_dump(self, *, exclude_none: bool = True) -> dict:
            return {"role": "assistant", "content": self.content}

    persisted: dict = {}
    statuses: list[str] = []

    async def fake_create(**_kwargs: object) -> object:
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5),
            choices=[SimpleNamespace(message=FakeMessage())],
        )

    async def fake_plan(*_args: object, **_kwargs: object) -> dict:
        return {"id": "plan-1", "status": "planned"}

    async def fake_update(_plan_id: str, _owner: str, *, status: str, **_kwargs: object) -> dict:
        statuses.append(status)
        return {"status": status}

    async def fake_persist(**kwargs: object) -> None:
        persisted.update(kwargs)

    async def empty_history() -> list[dict]:
        return []

    async def empty_snapshot() -> str:
        return ""

    async def empty_memory(*_args: object, **_kwargs: object) -> MemoryContext:
        return MemoryContext(text="", hits=0, chars=0)

    monkeypatch.setattr(agent_loop.llm.chat.completions, "create", fake_create)
    monkeypatch.setattr(agent_loop, "create_agent_plan", fake_plan)
    monkeypatch.setattr(agent_loop, "update_agent_plan", fake_update)
    monkeypatch.setattr(agent_loop, "append_agent_plan_evidence", lambda *_a, **_k: None)
    monkeypatch.setattr(agent_loop, "load_history", empty_history)
    monkeypatch.setattr(agent_loop, "load_work_snapshot", empty_snapshot)
    monkeypatch.setattr(agent_loop, "load_memory_context", empty_memory)
    monkeypatch.setattr(agent_loop, "persist_turn", fake_persist)
    monkeypatch.setattr(agent_loop, "current_model", lambda: "test-model")

    result = await agent_loop.run_agent(
        channel_id="channel-1",
        slack_user_id="owner-1",
        user_message="Investigate the failing GitHub watch job and implement a resilient fix.",
    )

    assert result["planId"] == "plan-1"
    assert result["planStatus"] == "completed"
    assert statuses == ["executing", "verifying", "completed"]
    assert "Execution controller" in persisted["messages"][0]["content"]
    assert persisted["plan_id"] == "plan-1"
    assert persisted["plan_status"] == "completed"
