from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from src.config import get_settings
from src.discord.service import handle_message


class FakeChannel:
    def __init__(self, channel_id: int = 99) -> None:
        self.id = channel_id
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    @asynccontextmanager
    async def typing(self):
        yield


class FakeMessage:
    def __init__(
        self,
        *,
        content: str = "hello",
        author_id: int = 123,
        bot: bool = False,
        guild: object | None = None,
        mentions: list[object] | None = None,
        attachments: list[object] | None = None,
    ) -> None:
        self.id = 1
        self.content = content
        self.author = SimpleNamespace(id=author_id, bot=bot)
        self.guild = guild
        self.mentions = mentions or []
        self.attachments = attachments or []
        self.channel = FakeChannel()
        self.reactions: list[str] = []

    async def add_reaction(self, emoji: str) -> None:
        self.reactions.append(emoji)


@pytest.fixture
def discord_owner(monkeypatch: pytest.MonkeyPatch) -> str:
    settings = get_settings()
    previous = (settings.DISCORD_BOT_TOKEN, settings.DISCORD_USER_ID)
    settings.DISCORD_BOT_TOKEN = "discord-test-token"
    settings.DISCORD_USER_ID = "123"
    yield "123"
    settings.DISCORD_BOT_TOKEN, settings.DISCORD_USER_ID = previous


@pytest.mark.asyncio
async def test_skips_bots(discord_owner: str) -> None:
    message = FakeMessage(bot=True)
    await handle_message(message, bot_user_id=9)
    assert message.channel.sent == []
    assert message.reactions == []


@pytest.mark.asyncio
async def test_skips_guild_message_without_mention(discord_owner: str) -> None:
    message = FakeMessage(guild=object())
    await handle_message(message, bot_user_id=9)
    assert message.channel.sent == []


@pytest.mark.asyncio
async def test_rejects_other_users_in_dm(discord_owner: str) -> None:
    message = FakeMessage(author_id=999)
    await handle_message(message, bot_user_id=9)
    assert message.channel.sent == ["This agent only responds to its configured Discord user."]


@pytest.mark.asyncio
async def test_runs_agent_for_owner_dm(discord_owner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_agent(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"text": "pong"}

    monkeypatch.setattr("src.discord.service.run_agent", fake_agent)
    message = FakeMessage(content="ping")
    await handle_message(message, bot_user_id=9)
    assert seen["channel_id"] == "discord:99"
    assert seen["slack_user_id"] == "123"
    assert seen["user_message"] == "ping"
    assert seen["surface"] == "discord"
    assert message.channel.sent == ["pong"]
    assert message.reactions == ["👀", "✅"]


@pytest.mark.asyncio
async def test_strips_mention_in_guild(discord_owner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_agent(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"text": "ok"}

    monkeypatch.setattr("src.discord.service.run_agent", fake_agent)
    message = FakeMessage(
        content="<@9> status please",
        guild=object(),
        mentions=[SimpleNamespace(id=9)],
    )
    await handle_message(message, bot_user_id=9)
    assert seen["user_message"] == "status please"
    assert message.channel.sent == ["ok"]


@pytest.mark.asyncio
async def test_google_connect_command(discord_owner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.discord.service.oauth_is_configured", lambda: True)
    monkeypatch.setattr(
        "src.discord.service.connect_message_markdown",
        lambda: "Connect link",
    )
    called = {"agent": False}

    async def fake_agent(**kwargs: object) -> dict[str, object]:
        called["agent"] = True
        return {"text": "nope"}

    monkeypatch.setattr("src.discord.service.run_agent", fake_agent)
    message = FakeMessage(content="connect google")
    await handle_message(message, bot_user_id=9)
    assert message.channel.sent == ["Connect link"]
    assert called["agent"] is False
