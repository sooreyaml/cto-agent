import pytest
from src.notify import notify_owner


@pytest.mark.asyncio
async def test_notify_owner_dms_discord_and_slack(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    async def fake_discord(user_id: str, text: str) -> None:
        seen["discord_user_id"] = user_id
        seen["discord_text"] = text

    async def fake_slack(user_id: str, text: str, *, mrkdwn: bool = False) -> None:
        seen["slack_user_id"] = user_id
        seen["slack_text"] = text
        seen["mrkdwn"] = str(mrkdwn)

    monkeypatch.setattr("src.discord.client.post_discord_dm", fake_discord)
    monkeypatch.setattr("src.slack.client.post_dm_to_user", fake_slack)
    await notify_owner("hello")
    assert seen["discord_user_id"] == "123"
    assert seen["discord_text"] == "hello"
    assert seen["slack_user_id"] == "UTEST"
    assert seen["slack_text"] == "hello"


@pytest.mark.asyncio
async def test_notify_owner_falls_back_to_slack(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    async def fake_discord(user_id: str, text: str) -> None:
        raise RuntimeError("Discord bot is not connected")

    async def fake_slack(user_id: str, text: str, *, mrkdwn: bool = False) -> None:
        seen["user_id"] = user_id
        seen["text"] = text

    monkeypatch.setattr("src.discord.client.post_discord_dm", fake_discord)
    monkeypatch.setattr("src.slack.client.post_dm_to_user", fake_slack)
    await notify_owner("hello")
    assert seen == {"user_id": "UTEST", "text": "hello"}


@pytest.mark.asyncio
async def test_notify_owner_raises_when_all_surfaces_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_discord(user_id: str, text: str) -> None:
        raise RuntimeError("Discord bot is not connected")

    async def fake_slack(user_id: str, text: str, *, mrkdwn: bool = False) -> None:
        raise RuntimeError("Slack is not configured")

    monkeypatch.setattr("src.discord.client.post_discord_dm", fake_discord)
    monkeypatch.setattr("src.slack.client.post_dm_to_user", fake_slack)
    with pytest.raises(RuntimeError, match="not connected"):
        await notify_owner("hello")
