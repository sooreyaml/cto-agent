import logging
from typing import Any

from src.connections.repository import resolve_token
from src.integrations.github import github_client
from src.notify import notify_owner
from src.tools.github import fetch_active_repos
from src.work.repository import record_watch_cursors, unseen_watch_ids

logger = logging.getLogger(__name__)
WATCH_SOURCE = "github_actions"


def failure_cursor_id(repo: str, run: dict[str, Any]) -> str | None:
    run_id = run.get("id")
    if run_id is None:
        return None
    return f"{repo}:{run_id}"


def format_watch_message(failures: list[dict[str, Any]]) -> str:
    lines = ["**CI failures**"]
    for item in failures:
        name = item.get("name") or "workflow"
        repo = item.get("repo")
        url = item.get("html_url")
        if url:
            lines.append(f"- [{repo} / {name}]({url})")
        else:
            lines.append(f"- {repo} / {name}")
    return "\n".join(lines)


async def collect_failed_runs() -> list[dict[str, Any]]:
    async with github_client() as client:
        repos = await fetch_active_repos(client)
        failures: list[dict[str, Any]] = []
        for repo in repos:
            owner = repo["owner"]
            name = repo["name"]
            full = repo["full_name"]
            branch = repo.get("default_branch") or "main"
            res = await client.get(
                f"/repos/{owner}/{name}/actions/runs",
                params={"branch": branch, "per_page": 8},
            )
            res.raise_for_status()
            for run in res.json().get("workflow_runs") or []:
                if run.get("conclusion") != "failure":
                    continue
                cursor = failure_cursor_id(full, run)
                if not cursor:
                    continue
                failures.append(
                    {
                        "cursor": cursor,
                        "repo": full,
                        "name": run.get("name"),
                        "html_url": run.get("html_url"),
                    }
                )
        return failures


async def run_watch() -> dict[str, int]:
    if not await resolve_token("github"):
        logger.info("watch skipped: GitHub not connected")
        return {"failures": 0, "notified": 0}
    failures = await collect_failed_runs()
    unseen = await unseen_watch_ids(WATCH_SOURCE, [item["cursor"] for item in failures])
    fresh = [item for item in failures if item["cursor"] in unseen]
    if fresh:
        await notify_owner(format_watch_message(fresh))
        await record_watch_cursors(WATCH_SOURCE, [item["cursor"] for item in fresh])
        logger.info("watch notified failures=%s", len(fresh))
    return {"failures": len(failures), "notified": len(fresh)}
