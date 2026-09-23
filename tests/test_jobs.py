import httpx
import pytest
import src.jobs.watch as watch
from src.jobs.due import format_due_message
from src.jobs.watch import WatchPoll, failure_cursor_id, format_watch_message


def test_format_due_message_none_when_empty() -> None:
    assert format_due_message({"reminders": [], "commitments": []}) is None


def test_format_due_message_lists_items() -> None:
    text = format_due_message(
        {
            "reminders": [{"message": "Prep board deck"}],
            "commitments": [{"who": "me", "what": "Send recap", "due_at": "2026-09-09T00:00:00"}],
        }
    )
    assert text is not None
    assert "Prep board deck" in text
    assert "Send recap" in text
    assert "due 2026-09-09" in text


def test_watch_cursor_and_message() -> None:
    assert failure_cursor_id("acme/api", {"id": 99}) == "acme/api:99"
    assert failure_cursor_id("acme/api", {}) is None
    text = format_watch_message(
        [
            {
                "repo": "acme/api",
                "name": "CI",
                "html_url": "https://github.com/acme/api/actions/runs/1",
            }
        ]
    )
    assert "**CI failures**" in text
    assert "acme/api / CI" in text

    repeated = format_watch_message(
        [
            {"repo": "acme/api", "workflow": "CI", "branch": "main", "run_id": 2},
            {"repo": "acme/api", "workflow": "CI", "branch": "main", "run_id": 1},
        ]
    )
    assert "Repeated failure: 2 runs" in repeated


@pytest.mark.asyncio
async def test_watch_turns_github_401_into_reconnect_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "https://api.github.com/user/repos")
    response = httpx.Response(401, request=request)

    async def fail() -> list[dict]:
        raise httpx.HTTPStatusError("expired", request=request, response=response)

    notices: list[str] = []

    async def notify(message: str) -> None:
        notices.append(message)

    monkeypatch.setattr(watch, "resolve_token", lambda *_args: _connected_token())
    monkeypatch.setattr(watch, "collect_failed_runs", fail)
    monkeypatch.setattr(watch, "notify_owner", notify)
    monkeypatch.setattr(watch, "_auth_notice_sent", False)

    assert await watch.run_watch() == {"failures": 0, "notified": 0}
    assert notices == [
        "**GitHub connection expired.** Say `connect github` in Discord and open the "
        "sign-in link. The CI watch will resume after reconnecting."
    ]


@pytest.mark.asyncio
async def test_watch_partial_poll_does_not_resolve_existing_incidents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = {
        "cursor": "acme/api:42",
        "external_id": "acme/api:42",
        "repo": "acme/api",
        "workflow": "CI",
        "html_url": "https://github.com/acme/api/actions/runs/42",
    }
    resolution: dict[str, object] = {}
    collected = [failure]

    async def collect() -> list[dict]:
        watch._last_poll = WatchPoll(
            failures=collected,
            polled_repositories=["acme/api"],
            complete=False,
            errors=["acme/other:500"],
        )
        return collected

    async def resolve(_owner: str, **kwargs: object) -> int:
        resolution.update(kwargs)
        return 0

    async def empty_bundle() -> dict:
        return {"priorities": [], "tasks": [], "commitments": []}

    monkeypatch.setattr(watch, "resolve_token", lambda *_args: _connected_token())
    monkeypatch.setattr(watch, "collect_failed_runs", collect)
    monkeypatch.setattr(watch, "unseen_watch_ids", lambda *_args: _empty_set())
    monkeypatch.setattr(watch, "brief_bundle", empty_bundle)
    monkeypatch.setattr(watch, "_persist_incidents", lambda *_args, **_kwargs: _empty_async())
    monkeypatch.setattr(watch, "resolve_ci_incidents_after_complete_poll", resolve)

    result = await watch.run_watch()

    assert result == {"failures": 1, "notified": 0}
    assert resolution["complete"] is False


async def _empty_set() -> set[str]:
    return set()


async def _empty_async() -> None:
    return None


async def _connected_token() -> str:
    return "stale-token"
