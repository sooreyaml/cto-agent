import asyncio

import pytest
import src.discord.client as discord_client
import src.main as main
from src.cron import tasks as cron_tasks


@pytest.mark.asyncio
async def test_discord_connection_does_not_block_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    class FakeDiscordClient:
        async def start(self, token: str) -> None:
            assert token == "discord-test-token"
            started.set()
            await stopped.wait()

        async def close(self) -> None:
            stopped.set()

        def is_closed(self) -> bool:
            return False

    client = FakeDiscordClient()
    monkeypatch.setattr(discord_client, "DiscordAgentClient", lambda **_kwargs: client)
    monkeypatch.setattr(discord_client, "_client", None)
    monkeypatch.setattr(discord_client, "_task", None)

    discord_client.start_discord_bot()
    await asyncio.wait_for(started.wait(), timeout=1)
    await discord_client.stop_discord_bot()


@pytest.mark.asyncio
async def test_spawn_cron_deduplicates_before_task_starts() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    name = "deduplication-test"

    async def job() -> None:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()

    cron_tasks.spawn_cron(name, job)
    cron_tasks.spawn_cron(name, job)
    await asyncio.wait_for(started.wait(), timeout=1)
    assert calls == 1

    release.set()
    for _ in range(10):
        if name not in cron_tasks._running:
            break
        await asyncio.sleep(0)
    assert name not in cron_tasks._running


@pytest.mark.asyncio
async def test_lifespan_bounds_database_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()
    discord_started = False

    async def stalled_ping() -> None:
        await never.wait()

    def start_discord() -> None:
        nonlocal discord_started
        discord_started = True

    async def stop_discord() -> None:
        return None

    monkeypatch.setattr(main, "DATABASE_STARTUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(main, "ping_db", stalled_ping)
    monkeypatch.setattr(main, "start_discord_bot", start_discord)
    monkeypatch.setattr(main, "stop_discord_bot", stop_discord)

    async with main.lifespan(main.app):
        assert discord_started
