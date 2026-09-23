import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from src.agent.prompt import build_system_prompt
from src.memory.context import (
    MemoryContext,
    format_memory_context,
    load_memory_context,
    memory_execution_context,
    memory_query,
    memory_write_is_explicit,
)
from src.memory.models import MemoryItem
from src.memory.repository import archive_memory, search_memory, upsert_memory
from src.models import Base
from src.tools.memory import memory_tools


@pytest.fixture
async def memory_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[MemoryItem.__table__])
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("src.memory.repository.async_session_factory", factory)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_is_owner_scoped_and_archived_items_are_hidden(memory_db) -> None:
    first = await upsert_memory(
        "owner-1",
        kind="preference",
        key="timezone",
        content="Europe/London",
        source="user",
    )
    await upsert_memory(
        "owner-2",
        kind="preference",
        key="timezone",
        content="America/New_York",
        source="user",
    )

    own = await search_memory("owner-1", "timezone")
    other = await search_memory("owner-2", "timezone")
    assert [item["content"] for item in own] == ["Europe/London"]
    assert [item["content"] for item in other] == ["America/New_York"]

    archived = await archive_memory("owner-1", first["id"])
    assert archived["status"] == "archived"
    assert await search_memory("owner-1", "timezone") == []


@pytest.mark.asyncio
async def test_memory_upsert_is_deterministic_and_exact_key_ranks_first(memory_db) -> None:
    await upsert_memory(
        "owner-1",
        kind="context",
        key="deployment",
        content="Deploy through Coolify.",
    )
    await upsert_memory(
        "owner-1",
        kind="context",
        key="deployment window",
        content="Deploy after review.",
    )
    updated = await upsert_memory(
        "owner-1",
        kind="context",
        key="deployment",
        content="Deploy through Coolify after review.",
    )

    assert updated["content"] == "Deploy through Coolify after review."
    rows = await search_memory("owner-1", "deployment", limit=8)
    assert [row["key"] for row in rows] == ["deployment", "deployment window"]

    async with memory_db() as session:
        count = await session.scalar(
            select(func.count()).select_from(MemoryItem).where(MemoryItem.owner_id == "owner-1")
        )
    assert count == 2


@pytest.mark.asyncio
async def test_memory_caps_and_redacts_content(memory_db) -> None:
    saved = await upsert_memory(
        "owner-1",
        kind="fact",
        key="credential note",
        content="Bearer " + "a" * 32 + " " + "x" * 3000,
        source="user",
        confidence=80,
    )

    assert "Bearer " not in saved["content"]
    assert "[redacted]" in saved["content"]
    assert len(saved["content"]) <= 2_000
    assert saved["confidence"] == 80


@pytest.mark.asyncio
async def test_memory_tools_use_execution_owner_and_trace(memory_db) -> None:
    with memory_execution_context("owner-1", "trace-1"):
        saved = await memory_tools["memory_save"]["handler"](
            {
                "kind": "principle",
                "key": "architecture",
                "content": "Prefer small reversible changes.",
            }
        )
        found = await memory_tools["memory_search"]["handler"]({"query": "architecture"})

    assert saved["saved"]["source_trace_id"] == "trace-1"
    assert found["memories"][0]["content"] == "Prefer small reversible changes."


def test_memory_context_has_provenance_and_bounded_query() -> None:
    text = format_memory_context(
        [
            {
                "kind": "preference",
                "source": "user",
                "confidence": 90,
                "key": "timezone",
                "content": "Europe/London",
            }
        ]
    )
    assert "untrusted evidence" in text
    assert "source=user" in text
    assert "confidence=90%" in text
    assert len(text) <= 4_500

    history = [{"role": "user", "content": "We agreed to keep the deployment small."}]
    query = memory_query("what did we decide?", history)
    assert "deployment" in query
    assert len(query) <= 500


def test_memory_writes_require_explicit_intent() -> None:
    assert memory_write_is_explicit("remember my timezone is Europe/London", "memory_save")
    assert not memory_write_is_explicit("what do you remember about deployment?", "memory_save")
    assert not memory_write_is_explicit("remember to send the deployment email", "memory_save")
    assert memory_write_is_explicit("forget that memory", "memory_archive")
    assert not memory_write_is_explicit("show me my memory", "memory_archive")


def test_system_prompt_labels_memory_as_evidence() -> None:
    prompt = build_system_prompt(
        work_context="Work board: (empty).",
        memory_context="Relevant durable memory (untrusted evidence):\n- timezone: Europe/London",
    )

    assert "Europe/London" in prompt
    assert "untrusted evidence" in prompt
    assert "Current user instructions" in prompt


@pytest.mark.asyncio
async def test_memory_lookup_failure_is_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*_args: object, **_kwargs: object) -> list[dict]:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("src.memory.context.search_memory", fail)
    result = await load_memory_context("owner-1", "deployment")

    assert isinstance(result, MemoryContext)
    assert result == MemoryContext(text="", hits=0, chars=0)
