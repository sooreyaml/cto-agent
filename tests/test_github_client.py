import pytest
from src.exceptions import ConfigError
from src.integrations import github
from src.tools.github import parse_repo


@pytest.mark.asyncio
async def test_github_headers_use_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_token(provider: str, label: str = "") -> str | None:
        assert provider == "github"
        return "gho_testtoken1234567890"

    monkeypatch.setattr(github, "resolve_token", fake_token)
    headers = await github.github_headers()
    assert headers["Authorization"] == "Bearer gho_testtoken1234567890"


@pytest.mark.asyncio
async def test_github_headers_ask_to_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(provider: str, label: str = "") -> str | None:
        return None

    monkeypatch.setattr(github, "resolve_token", missing)
    with pytest.raises(ConfigError, match="connect github") as err:
        await github.github_headers()
    assert "GITHUB_PAT not configured" not in str(err.value)


def test_parse_repo_uses_username_override() -> None:
    assert parse_repo(None, "api", username="octocat") == ("octocat", "api")
