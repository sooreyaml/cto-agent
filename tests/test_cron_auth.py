import pytest
from httpx import ASGITransport, AsyncClient
from src.main import app

AUTH = {"Authorization": "Bearer cron-test-secret"}
HEADER = {"X-Cron-Secret": "cron-test-secret"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/cron/daily-brief", "/cron/due", "/cron/watch"])
async def test_cron_unauthorized(path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(path)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_cron_rejects_wrong_secret() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/cron/due", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_cron_accepts_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_due() -> dict[str, int]:
        return {"reminders": 0, "commitments": 0}

    monkeypatch.setattr("src.cron.router.run_due", fake_due)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/cron/due", headers=AUTH)
    assert res.status_code == 200
    assert res.json() == {"ok": True, "reminders": 0, "commitments": 0}


@pytest.mark.asyncio
async def test_cron_accepts_x_cron_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_watch() -> dict[str, int]:
        return {"failures": 0, "notified": 0}

    monkeypatch.setattr("src.cron.router.run_watch", fake_watch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/cron/watch", headers=HEADER)
    assert res.status_code == 200
    assert res.json() == {"ok": True, "failures": 0, "notified": 0}
