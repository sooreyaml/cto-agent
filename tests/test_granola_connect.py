import pytest
from src.connections.catalog import get_provider
from src.exceptions import ConfigError
from src.integrations import granola
from src.integrations.granola_mcp import path_to_mcp


@pytest.mark.asyncio
async def test_granola_uses_saved_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ready() -> tuple[str, dict]:
        return "granola-test-token", {"base_url": "https://api.granola.ai"}

    class FakeResponse:
        status_code = 200
        text = '{"meetings":[]}'

        def json(self):
            return {"meetings": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            assert url == "https://api.granola.ai/meetings?limit=5"
            assert headers["Authorization"] == "Bearer granola-test-token"
            return FakeResponse()

    monkeypatch.setattr(granola, "ready_granola", fake_ready)
    monkeypatch.setattr(granola.httpx, "AsyncClient", FakeClient)
    data = await granola.granola_request("/meetings?limit=5")
    assert data == {"meetings": []}


@pytest.mark.asyncio
async def test_granola_oauth_uses_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ready() -> tuple[str, dict]:
        return "mcp-access", {"kind": "mcp_oauth", "mcp_url": "https://mcp.granola.ai/mcp"}

    async def fake_mcp(token: str, extra: dict, name: str, args: dict) -> dict:
        assert token == "mcp-access"
        assert name == "list_meetings"
        assert args["limit"] == 5
        return {"meetings": [{"id": "1"}]}

    monkeypatch.setattr(granola, "ready_granola", fake_ready)
    monkeypatch.setattr(granola, "call_granola_tool", fake_mcp)
    data = await granola.granola_request("/meetings?limit=5")
    assert data == {"meetings": [{"id": "1"}]}


@pytest.mark.asyncio
async def test_granola_asks_to_connect_not_env(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing() -> tuple[str, dict]:
        raise ConfigError(
            "Granola is not connected. Ask the user to say “connect granola” in Discord "
            "and open the sign-in link. Do not tell them to edit .env."
        )

    monkeypatch.setattr(granola, "ready_granola", missing)
    with pytest.raises(ConfigError, match="connect granola") as err:
        await granola.granola_request("/meetings")
    assert ".env" in str(err.value)
    assert "GRANOLA_API_KEY not configured" not in str(err.value)


def test_granola_is_in_catalog() -> None:
    spec = get_provider("granola")
    assert spec["auth"] == "oauth"
    assert spec["base_url"] == "https://mcp.granola.ai"


def test_path_to_mcp() -> None:
    name, args = path_to_mcp("/meetings?limit=5")
    assert name == "list_meetings"
    assert args["limit"] == 5
    name, args = path_to_mcp("/meetings/abc-123")
    assert name == "get_meetings"
    assert args["id"] == "abc-123"
    name, args = path_to_mcp("/search?q=launch")
    assert name == "query_granola_meetings"
    assert args["query"] == "launch"
