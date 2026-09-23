"""Provider-neutral CI evidence compaction and deterministic signals."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from src.connections.redact import redact_obj, redact_secrets

MAX_JOB_RESULTS = 8
MAX_FAILED_STEPS = 5
MAX_PULL_REQUESTS = 5
MAX_EVIDENCE_CHARS = 4_000
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _text(value: object, max_chars: int = 240) -> str | None:
    if value is None:
        return None
    text = redact_secrets(str(value).strip())
    return text[:max_chars] or None


def _run_id(value: object) -> int | None:
    try:
        run_id = int(value)
    except (TypeError, ValueError):
        return None
    return run_id if run_id > 0 else None


def _pull_request(pr: dict[str, Any]) -> dict[str, Any]:
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    return {
        "number": _run_id(pr.get("number")),
        "title": _text(pr.get("title"), 240),
        "url": _text(pr.get("html_url"), 500),
        "branch": _text(head.get("ref"), 160),
    }


def normalise_workflow_run(repo: dict[str, Any], run: dict[str, Any]) -> dict[str, Any] | None:
    """Extract bounded metadata from one failed workflow run."""

    full_name = _text(repo.get("full_name"), 240)
    run_id = _run_id(run.get("id"))
    if not full_name or not run_id:
        return None
    raw_owner = repo.get("owner")
    owner = raw_owner.get("login") if isinstance(raw_owner, dict) else raw_owner
    raw_name = repo.get("name")
    name = raw_name.get("name") if isinstance(raw_name, dict) else raw_name
    head_commit = run.get("head_commit") if isinstance(run.get("head_commit"), dict) else {}
    raw_pull_requests = run.get("pull_requests")
    pull_request_items = raw_pull_requests if isinstance(raw_pull_requests, list) else []
    pull_requests = [
        _pull_request(pr) for pr in pull_request_items[:MAX_PULL_REQUESTS] if isinstance(pr, dict)
    ]
    return {
        "cursor": f"{full_name}:{run_id}",
        "external_id": f"{full_name}:{run_id}",
        "repo": full_name,
        "owner": _text(owner, 160) or full_name.split("/", 1)[0],
        "repo_name": _text(name, 160) or full_name.rsplit("/", 1)[-1],
        "workflow": _text(run.get("name"), 200) or "workflow",
        "name": _text(run.get("name"), 200) or "workflow",
        "run_id": run_id,
        "run_number": _run_id(run.get("run_number")),
        "status": _text(run.get("status"), 40),
        "conclusion": _text(run.get("conclusion"), 40),
        "branch": _text(run.get("head_branch"), 160),
        "default_branch": _text(repo.get("default_branch"), 160) or "main",
        "head_sha": _text(run.get("head_sha"), 80),
        "commit_message": _text(head_commit.get("message"), 500),
        "created_at": _text(run.get("created_at"), 80),
        "updated_at": _text(run.get("updated_at"), 80),
        "html_url": _text(run.get("html_url"), 500),
        "pull_requests": pull_requests,
    }


def compact_workflow_run(run: dict[str, Any]) -> dict[str, Any]:
    """Compact a run returned by a read-only GitHub tool."""

    repository = run.get("repository") if isinstance(run.get("repository"), dict) else {}
    repository_owner = repository.get("owner") if isinstance(repository.get("owner"), dict) else {}
    normalized = normalise_workflow_run(
        {
            "full_name": repository.get("full_name") or run.get("repo"),
            "owner": repository_owner.get("login") or run.get("owner"),
            "name": repository.get("name") or run.get("repo_name"),
            "default_branch": repository.get("default_branch") or run.get("default_branch"),
        },
        run,
    )
    return normalized or {
        "workflow": _text(run.get("name"), 200) or "workflow",
        "run_id": _run_id(run.get("id")),
        "status": _text(run.get("status"), 40),
        "conclusion": _text(run.get("conclusion"), 40),
        "branch": _text(run.get("head_branch"), 160),
        "head_sha": _text(run.get("head_sha"), 80),
        "html_url": _text(run.get("html_url"), 500),
        "created_at": _text(run.get("created_at"), 80),
    }


def compact_workflow_jobs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep job names, conclusions and failed step names; never raw logs."""

    if not isinstance(payload, dict):
        return []
    jobs: list[dict[str, Any]] = []
    for job in (payload.get("jobs") or [])[:MAX_JOB_RESULTS]:
        if not isinstance(job, dict):
            continue
        steps: list[dict[str, Any]] = []
        for step in (job.get("steps") or [])[: MAX_FAILED_STEPS * 2]:
            if not isinstance(step, dict):
                continue
            conclusion = _text(step.get("conclusion"), 40)
            if conclusion not in {"failure", "cancelled", "timed_out", "startup_failure"}:
                continue
            steps.append(
                {
                    "name": _text(step.get("name"), 240) or "step",
                    "conclusion": conclusion,
                    "number": _run_id(step.get("number")),
                }
            )
            if len(steps) >= MAX_FAILED_STEPS:
                break
        conclusion = _text(job.get("conclusion"), 40)
        if conclusion == "success" and not steps:
            continue
        jobs.append(
            {
                "name": _text(job.get("name"), 240) or "job",
                "conclusion": conclusion,
                "status": _text(job.get("status"), 40),
                "url": _text(job.get("html_url"), 500),
                "failed_steps": steps,
            }
        )
    return jobs


def classify_failure_signal(jobs: list[dict[str, Any]]) -> dict[str, str]:
    evidence = " ".join(
        [
            str(job.get("name") or "")
            + " "
            + " ".join(str(step.get("name") or "") for step in job.get("failed_steps") or [])
            for job in jobs
        ]
    ).lower()
    categories = (
        (
            ("auth", "permission", "token", "401", "403"),
            "Authentication or permission gate",
            "Check workflow token permissions and secret access before rerunning.",
        ),
        (
            ("timeout", "network", "connection", "rate limit"),
            "Infrastructure or network gate",
            "Inspect the first timeout or network error and check service health.",
        ),
        (
            ("deploy", "release", "publish", "terraform", "docker"),
            "Deployment or release gate",
            "Compare the release diff and verify deployment environment configuration.",
        ),
        (
            ("build", "compile", "install", "dependency", "npm", "pip"),
            "Build or dependency gate",
            "Compare lockfiles and runtime image changes around the failing commit.",
        ),
        (
            ("test", "pytest", "jest", "lint", "typecheck", "type check", "quality"),
            "Test or quality gate",
            "Open the failed job and inspect the first failing test, lint, or type-check step.",
        ),
    )
    for terms, category, next_diagnostic in categories:
        if any(term in evidence for term in terms):
            return {
                "category": category,
                "likely_cause": f"The failure is most consistent with a {category.lower()} based on failed job or step names.",
                "next_diagnostic": next_diagnostic,
            }
    return {
        "category": "Unclassified CI failure",
        "likely_cause": "The failed job metadata is insufficient to infer a likely cause.",
        "next_diagnostic": "Open the failed job logs and inspect the first failing step.",
    }


def classify_ci_severity(
    failure: dict[str, Any],
    *,
    failure_streak: int = 1,
    workflow_count: int = 1,
) -> str:
    try:
        streak = max(int(failure_streak), 1)
    except (TypeError, ValueError):
        streak = 1
    try:
        workflows = max(int(workflow_count), 1)
    except (TypeError, ValueError):
        workflows = 1
    branch = str(failure.get("branch") or "").strip()
    default_branch = str(failure.get("default_branch") or "main").strip()
    if branch == default_branch and (streak >= 2 or workflows >= 2):
        return "critical"
    if branch == default_branch:
        return "high"
    if streak >= 2:
        return "medium"
    return "low"


def group_repeated_failures(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for failure in failures:
        key = (
            str(failure.get("repo") or ""),
            str(failure.get("workflow") or failure.get("name") or "workflow"),
            str(failure.get("branch") or ""),
        )
        groups[key].append(failure)
    return [
        {
            "repo": key[0],
            "workflow": key[1],
            "branch": key[2],
            "count": len(items),
            "run_ids": [item.get("run_id") for item in items[:10]],
            "latest_url": items[0].get("html_url"),
        }
        for key, items in groups.items()
    ]


def build_incident_actions(failure: dict[str, Any]) -> list[dict[str, Any]]:
    signal = failure.get("failure_signal") or classify_failure_signal(
        failure.get("failed_jobs") or []
    )
    url = failure.get("html_url")
    return [
        {
            "priority": "high" if failure.get("severity") in {"critical", "high"} else "medium",
            "action": f"Investigate failing {failure.get('repo') or 'repository'} workflow",
            "reason": signal.get("likely_cause"),
            "source": "github",
            "evidence_url": url,
            "confidence": "high" if failure.get("failed_jobs") else "medium",
            "next_diagnostic": signal.get("next_diagnostic"),
        }
    ]


def verify_incident_evidence(failure: dict[str, Any]) -> bool:
    return bool(
        failure.get("repo")
        and failure.get("workflow")
        and failure.get("external_id")
        and failure.get("html_url")
        and (failure.get("failed_jobs") is not None)
    )


def incident_evidence(failure: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "branch": failure.get("branch"),
        "default_branch": failure.get("default_branch"),
        "head_sha": failure.get("head_sha"),
        "commit_message": failure.get("commit_message"),
        "created_at": failure.get("created_at"),
        "failed_jobs": failure.get("failed_jobs") or [],
        "pull_requests": failure.get("pull_requests") or [],
        "failure_signal": failure.get("failure_signal") or {},
        "next_diagnostic": failure.get("next_diagnostic"),
    }
    safe = redact_obj(evidence)
    encoded = json.dumps(safe, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) <= MAX_EVIDENCE_CHARS:
        return safe if isinstance(safe, dict) else {"evidence": encoded}
    marker = " [truncated]"
    return {
        "evidence": encoded[: max(MAX_EVIDENCE_CHARS - len(marker), 0)] + marker,
        "truncated": True,
    }
