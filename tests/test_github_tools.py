from datetime import UTC, datetime

import pytest
from src.exceptions import ConfigError
from src.tools.github import (
    compact_issue,
    compact_repo,
    parse_repo,
    repo_from_repository_url,
    select_active_repos,
)

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _repo(
    full_name: str,
    pushed_at: str,
    *,
    archived: bool = False,
    disabled: bool = False,
) -> dict:
    owner, _, name = full_name.partition("/")
    return {
        "full_name": full_name,
        "pushed_at": pushed_at,
        "archived": archived,
        "disabled": disabled,
        "private": False,
        "fork": False,
        "default_branch": "main",
        "language": "Python",
        "open_issues_count": 2,
        "html_url": f"https://github.com/{full_name}",
        "description": "demo",
        "owner": {"login": owner},
        "name": name,
    }


def test_parse_repo_explicit() -> None:
    assert parse_repo("acme", "api") == ("acme", "api")


def test_parse_repo_requires_owner_and_repo() -> None:
    with pytest.raises(ConfigError, match="owner and repo"):
        parse_repo(None, None)


def test_select_active_repos_keeps_recent_and_skips_archived() -> None:
    repos = [
        _repo("acme/old", "2026-01-01T00:00:00Z"),
        _repo("acme/gone", "2026-09-04T00:00:00Z", archived=True),
        _repo("acme/hot", "2026-09-04T00:00:00Z"),
        _repo("acme/warm", "2026-08-28T00:00:00Z"),
    ]
    selected = select_active_repos(repos, now=NOW, days=14, limit=10)
    assert [r["full_name"] for r in selected] == ["acme/hot", "acme/warm"]


def test_select_active_repos_falls_back_when_none_recent() -> None:
    repos = [
        _repo("acme/a", "2025-01-01T00:00:00Z"),
        _repo("acme/b", "2025-06-01T00:00:00Z"),
    ]
    selected = select_active_repos(repos, now=NOW, days=14, limit=1)
    assert [r["full_name"] for r in selected] == ["acme/b"]


def test_compact_repo_and_issue() -> None:
    compact = compact_repo(_repo("acme/api", "2026-09-04T00:00:00Z"))
    assert compact["owner"] == "acme"
    assert compact["name"] == "api"
    assert compact["default_branch"] == "main"
    assert repo_from_repository_url("https://api.github.com/repos/acme/api") == "acme/api"
    issue = compact_issue(
        {
            "repository_url": "https://api.github.com/repos/acme/api",
            "number": 12,
            "title": "Fix CI",
            "state": "open",
            "html_url": "https://github.com/acme/api/pull/12",
            "user": {"login": "soore"},
            "pull_request": {"url": "https://api.github.com/repos/acme/api/pulls/12"},
            "updated_at": "2026-09-04T00:00:00Z",
            "labels": [{"name": "bug"}],
        }
    )
    assert issue["repo"] == "acme/api"
    assert issue["is_pull_request"] is True
    assert issue["labels"] == ["bug"]
