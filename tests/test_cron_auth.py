import pytest
from httpx import ASGITransport, AsyncClient
from src.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/cron/daily-brief", "/cron/due", "/cron/watch"])
async def test_cron_unauthorized(path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(path)
    assert res.status_code == 401
