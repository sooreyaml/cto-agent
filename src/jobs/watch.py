import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.ci.github import investigate_workflow_runs
from src.ci.intelligence import (
    build_incident_actions,
    classify_ci_severity,
    group_repeated_failures,
    normalise_workflow_run,
)
from src.ci.repository import (
    mark_ci_incidents_notified,
    resolve_ci_incidents_after_complete_poll,
    upsert_ci_incident,
)
from src.config import get_settings
from src.connections.repository import resolve_token
from src.integrations.github import github_client
from src.notify import notify_owner
from src.tools.github import fetch_active_repos
from src.work.repository import brief_bundle, record_watch_cursors, unseen_watch_ids

logger = logging.getLogger(__name__)
WATCH_SOURCE = "github_actions"
_auth_notice_sent = False


@dataclass
class WatchPoll:
    failures: list[dict[str, Any]] = field(default_factory=list)
    polled_repositories: list[str] = field(default_factory=list)
    complete: bool = True
    auth_error: bool = False
    errors: list[str] = field(default_factory=list)


_last_poll = WatchPoll()


async def _notify_auth_expired() -> None:
    global _auth_notice_sent
    if _auth_notice_sent:
        logger.info("watch auth notice already sent; waiting for GitHub reconnect")
        return
    try:
        await notify_owner(
            "**GitHub connection expired.** Say `connect github` in Discord and open the "
            "sign-in link. The CI watch will resume after reconnecting."
        )
        _auth_notice_sent = True
    except Exception:
        logger.exception("failed to notify owner about expired GitHub connection")


def failure_cursor_id(repo: str, run: dict[str, Any]) -> str | None:
    if not isinstance(run, dict):
        return None
    external_id = run.get("external_id") or run.get("cursor")
    if external_id:
        return str(external_id)
    run_id = run.get("id") or run.get("run_id")
    if run_id is None:
        return None
    return f"{repo}:{run_id}"


def _related_work(repo: str, work: dict[str, Any]) -> list[dict[str, Any]]:
    """Match incidents to explicit work-board text without inventing ownership."""

    if not isinstance(work, dict):
        return []
    full = (repo or "").lower()
    short = full.rsplit("/", 1)[-1]
    if not full or len(short) < 4:
        return []
    matches: list[dict[str, Any]] = []
    for kind in ("priorities", "tasks", "commitments"):
        for item in work.get(kind) or []:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                str(item.get(key) or "") for key in ("title", "what", "project", "notes")
            )
            lowered = text.lower()
            project = str(item.get("project") or "").strip().lower()
            if full not in lowered and project not in {full, short}:
                continue
            matches.append(
                {
                    "kind": kind[:-1],
                    "title": item.get("title") or item.get("what"),
                    "status": item.get("status"),
                    "id": item.get("id"),
                }
            )
            if len(matches) >= 3:
                return matches
    return matches


def format_watch_message(failures: list[dict[str, Any]]) -> str:
    lines = ["**CI failures** — incident summary"]
    repeated = {
        (group["repo"], group["workflow"], group["branch"]): group["count"]
        for group in group_repeated_failures(failures)
        if group["count"] > 1
    }
    for item in failures:
        name = item.get("name") or item.get("workflow") or "workflow"
        repo = item.get("repo") or "repository"
        severity = item.get("severity") or classify_ci_severity(item)
        url = item.get("html_url")
        heading = f"{repo} / {name} ({severity})"
        lines.append(f"- [{heading}]({url})" if url else f"- {heading}")
        repeat_count = repeated.get((repo, item.get("workflow") or name, item.get("branch") or ""))
        if repeat_count:
            lines.append(f"  - Repeated failure: {repeat_count} runs on this branch")
        signal = item.get("failure_signal") if isinstance(item.get("failure_signal"), dict) else {}
        if signal.get("category"):
            lines.append(f"  - Signal: {signal['category']}")
        jobs = item.get("failed_jobs") or []
        failed_labels = []
        for job in jobs[:4] if isinstance(jobs, list) else []:
            if not isinstance(job, dict):
                continue
            steps = ", ".join(
                str(step.get("name") or "step")
                for step in (job.get("failed_steps") or [])
                if isinstance(step, dict)
            )
            failed_labels.append(f"{job.get('name') or 'job'}" + (f" ({steps})" if steps else ""))
        if failed_labels:
            lines.append(f"  - Failed jobs/steps: {'; '.join(failed_labels)}")
        if item.get("commit_message"):
            lines.append(f"  - Commit: {item['commit_message'][:180]}")
        pull_requests = item.get("pull_requests") or []
        if isinstance(pull_requests, list) and pull_requests and isinstance(pull_requests[0], dict):
            pr = pull_requests[0]
            pr_text = f"PR #{pr.get('number')}: {pr.get('title') or 'related change'}"
            if pr.get("url"):
                lines.append(f"  - Related change: [{pr_text}]({pr['url']})")
            else:
                lines.append(f"  - Related change: {pr_text}")
        if signal.get("likely_cause"):
            lines.append(f"  - Inference: {signal['likely_cause']}")
        if signal.get("next_diagnostic"):
            lines.append(f"  - Next: {signal['next_diagnostic']}")
        related_work = item.get("related_work") or []
        if isinstance(related_work, list) and related_work and isinstance(related_work[0], dict):
            work = related_work[0]
            lines.append(f"  - Related work: {work.get('title')} ({work.get('status') or 'open'})")
        if item.get("jobs_error"):
            lines.append("  - Evidence gap: failed-job metadata was unavailable.")
    text = "\n".join(lines)
    if len(text) <= 1_900:
        return text
    marker = "\n…additional incidents omitted; open the workflow links for the full list."
    return text[: 1_900 - len(marker)].rstrip() + marker


async def collect_failed_runs_detailed() -> WatchPoll:
    async with github_client() as client:
        try:
            repos = await fetch_active_repos(client)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403, 429}:
                return WatchPoll(
                    complete=False,
                    auth_error=status == 401,
                    errors=[str(status)],
                )
            raise
        failures: list[dict[str, Any]] = []
        polled_repositories: list[str] = []
        errors: list[str] = []
        for repo in repos:
            if not isinstance(repo, dict):
                errors.append("invalid_repository")
                continue
            owner = str(repo.get("owner") or "").strip()
            name = str(repo.get("name") or "").strip()
            full = str(repo.get("full_name") or "").strip()
            if not owner or not name or not full:
                errors.append("invalid_repository")
                continue
            polled_repositories.append(full)
            branch = repo.get("default_branch") or "main"
            try:
                response = await client.get(
                    f"/repos/{owner}/{name}/actions/runs",
                    params={"branch": branch, "per_page": 8},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                errors.append(f"{full}:{exc.response.status_code}")
                if exc.response.status_code == 401:
                    return WatchPoll(
                        failures=failures,
                        polled_repositories=polled_repositories,
                        complete=False,
                        auth_error=True,
                        errors=errors,
                    )
                continue
            except Exception as exc:
                errors.append(f"{full}:{type(exc).__name__}")
                continue
            try:
                payload = response.json()
            except Exception as exc:
                errors.append(f"{full}:{type(exc).__name__}")
                continue
            if not isinstance(payload, dict):
                errors.append(f"{full}:invalid_payload")
                continue
            for run in payload.get("workflow_runs") or []:
                if not isinstance(run, dict):
                    continue
                if run.get("conclusion") != "failure":
                    continue
                normalized = normalise_workflow_run(repo, run)
                if normalized is not None:
                    failures.append(normalized)
        return WatchPoll(
            failures=failures,
            polled_repositories=polled_repositories,
            complete=not errors,
            errors=errors,
        )


async def collect_failed_runs() -> list[dict[str, Any]]:
    global _last_poll
    _last_poll = await collect_failed_runs_detailed()
    return _last_poll.failures


async def _persist_incidents(
    failures: list[dict[str, Any]],
    *,
    owner_id: str,
) -> None:
    for failure in failures:
        try:
            incident = await upsert_ci_incident(owner_id, failure)
            failure["severity"] = incident["severity"]
            failure["failure_streak"] = incident["failure_streak"]
        except Exception:
            logger.exception(
                "CI incident persistence failed external_id=%s", failure.get("external_id")
            )


async def run_watch() -> dict[str, int]:
    global _auth_notice_sent
    if not await resolve_token("github"):
        logger.info("watch skipped: GitHub not connected")
        return {"failures": 0, "notified": 0}
    try:
        failures = await collect_failed_runs()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {401, 403, 429}:
            raise
        status = exc.response.status_code
        logger.warning("watch skipped: GitHub poll rejected status=%s", status)
        if status == 401:
            await _notify_auth_expired()
        return {"failures": 0, "notified": 0}
    poll = _last_poll
    if poll.failures is not failures:
        # Collector overrides (including tests) should not inherit a stale
        # auth or partial-poll state from an earlier invocation.
        poll = WatchPoll(failures=failures)
    if poll.auth_error:
        logger.warning("watch skipped: GitHub authorization rejected during repository poll")
        await _notify_auth_expired()
        return {"failures": len(failures), "notified": 0}
    _auth_notice_sent = False
    if poll.errors:
        logger.warning("watch partial GitHub poll errors=%s", len(poll.errors))

    failures = [item for item in failures if isinstance(item, dict)]
    cursors = [failure_cursor_id(str(item.get("repo") or ""), item) for item in failures]
    valid_cursors = [cursor for cursor in cursors if cursor]
    unseen = await unseen_watch_ids(WATCH_SOURCE, valid_cursors)
    fresh = [
        item for item in failures if failure_cursor_id(str(item.get("repo") or ""), item) in unseen
    ]

    enriched = list(fresh)
    if fresh:
        try:
            async with github_client() as client:
                enriched = await investigate_workflow_runs(client, fresh, limit=5)
        except Exception:
            logger.exception("CI incident investigation failed; notifying with run metadata")
    by_cursor = {
        failure_cursor_id(str(item.get("repo") or ""), item): item
        for item in enriched
        if isinstance(item, dict)
    }
    failures = [
        by_cursor.get(failure_cursor_id(str(item.get("repo") or ""), item), item)
        for item in failures
        if isinstance(item, dict)
    ]

    work: dict[str, Any] = {}
    try:
        work = await brief_bundle()
    except Exception:
        logger.exception("watch could not load work context for incident correlation")
    for item in failures:
        item["related_work"] = _related_work(item.get("repo") or "", work)
        item["recommended_actions"] = build_incident_actions(item)

    settings = get_settings()
    await _persist_incidents(failures, owner_id=settings.owner_user_id)
    try:
        await resolve_ci_incidents_after_complete_poll(
            settings.owner_user_id,
            polled_repositories=poll.polled_repositories,
            seen_external_ids=[item.get("external_id") or item.get("cursor") for item in failures],
            complete=poll.complete,
        )
    except Exception:
        logger.exception("CI incident resolution failed")

    if fresh:
        await notify_owner(format_watch_message(enriched))
        await record_watch_cursors(
            WATCH_SOURCE,
            [str(item.get("cursor")) for item in fresh if item.get("cursor")],
        )
        try:
            await mark_ci_incidents_notified(
                settings.owner_user_id,
                [item.get("external_id") or item.get("cursor") for item in fresh],
            )
        except Exception:
            logger.exception("CI incident notification metadata update failed")
        logger.info("watch notified failures=%s", len(fresh))
    return {"failures": len(failures), "notified": len(fresh)}
