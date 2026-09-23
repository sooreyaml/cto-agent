"""Bounded GitHub Actions investigation calls."""

from __future__ import annotations

from typing import Any

from src.ci.intelligence import (
    classify_failure_signal,
    compact_workflow_jobs,
)
from src.connections.redact import redact_secrets


def _safe_text(value: object, max_chars: int) -> str | None:
    text = redact_secrets(str(value or "").strip())[:max_chars]
    return text or None


async def investigate_workflow_run(client: Any, failure: dict[str, Any]) -> dict[str, Any]:
    """Enrich a normalized run with jobs and related pull requests, never logs."""

    enriched = {
        key: value
        for key, value in failure.items()
        if key not in {"logs", "log", "raw_logs", "steps"}
    }
    owner = failure.get("owner")
    repo = failure.get("repo_name")
    run_id = failure.get("run_id")
    jobs: list[dict[str, Any]] = []
    if owner and repo and run_id:
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
                params={"per_page": 20},
            )
            response.raise_for_status()
            payload = response.json()
            jobs = compact_workflow_jobs(payload if isinstance(payload, dict) else {})
        except Exception as err:
            enriched["jobs_error"] = type(err).__name__
    enriched["failed_jobs"] = jobs

    if not enriched.get("pull_requests") and owner and repo and failure.get("head_sha"):
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/commits/{failure['head_sha']}/pulls",
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            payload = response.json()
            enriched["pull_requests"] = []
            for pr in (payload if isinstance(payload, list) else [])[:5]:
                if not isinstance(pr, dict):
                    continue
                head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
                enriched["pull_requests"].append(
                    {
                        "number": pr.get("number"),
                        "title": _safe_text(pr.get("title"), 240),
                        "url": _safe_text(pr.get("html_url"), 500),
                        "branch": _safe_text(head.get("ref"), 160),
                    }
                )
        except Exception as err:
            enriched["pull_requests_error"] = type(err).__name__

    enriched["failure_signal"] = classify_failure_signal(jobs)
    enriched["next_diagnostic"] = enriched["failure_signal"]["next_diagnostic"]
    return enriched


async def investigate_workflow_runs(
    client: Any,
    failures: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    try:
        bounded_limit = max(int(limit), 0)
    except (TypeError, ValueError):
        bounded_limit = 5
    enriched: list[dict[str, Any]] = []
    for failure in failures[:bounded_limit]:
        enriched.append(await investigate_workflow_run(client, failure))
    enriched.extend(failures[bounded_limit:])
    return enriched
