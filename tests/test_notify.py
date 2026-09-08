import pytest
from src.notify import notify_owner


@pytest.mark.asyncio
async def test_notify_owner_dms_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    async def fake_dm(user_id: str, text: str) -> None:
        seen["user_id"] = user_id
        seen["text"] = text

    monkeypatch.setattr("src.notify.post_discord_dm", fake_dm)
    await notify_owner("hello")
    assert seen == {"user_id": "123", "text": "hello"}


@pytest.mark.asyncio
async def test_notify_owner_raises_when_discord_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dm(user_id: str, text: str) -> None:
        raise RuntimeError("Discord bot is not connected")

    monkeypatch.setattr("src.notify.post_discord_dm", fake_dm)
    with pytest.raises(RuntimeError, match="not connected"):
        await notify_owner("hello")
