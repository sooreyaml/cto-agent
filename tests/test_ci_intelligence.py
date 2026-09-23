from src.ci.github import investigate_workflow_run
from src.ci.intelligence import (
    MAX_EVIDENCE_CHARS,
    build_incident_actions,
    classify_ci_severity,
    classify_failure_signal,
    compact_workflow_jobs,
    group_repeated_failures,
    incident_evidence,
    normalise_workflow_run,
    verify_incident_evidence,
)


def _repo() -> dict:
    return {
        "full_name": "acme/api",
        "owner": "acme",
        "name": "api",
        "default_branch": "main",
    }


def _run(run_id: int = 42) -> dict:
    return {
        "id": run_id,
        "run_number": 7,
        "name": "CI",
        "status": "completed",
        "conclusion": "failure",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "head_commit": {"message": "Fix deployment"},
        "html_url": f"https://github.com/acme/api/actions/runs/{run_id}",
        "pull_requests": [
            {
                "number": 8,
                "title": "Fix deployment",
                "html_url": "https://github.com/acme/api/pull/8",
                "head": {"ref": "fix-deploy"},
            }
        ],
    }


def test_normalise_run_is_bounded_and_has_stable_external_id() -> None:
    normalized = normalise_workflow_run(_repo(), _run())

    assert normalized is not None
    assert normalized["external_id"] == "acme/api:42"
    assert normalized["repo_name"] == "api"
    assert normalized["pull_requests"][0]["branch"] == "fix-deploy"


def test_job_compaction_excludes_raw_logs_and_classifies_auth() -> None:
    jobs = compact_workflow_jobs(
        {
            "jobs": [
                {
                    "name": "deploy",
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "https://github.com/acme/api/actions/runs/42/job/1",
                    "logs": "Bearer " + "a" * 40,
                    "steps": [
                        {"name": "Check token permission", "number": 1, "conclusion": "failure"},
                        {"name": "Never reached", "number": 2, "conclusion": "success"},
                    ],
                }
            ]
        }
    )

    assert jobs[0]["failed_steps"][0]["name"] == "Check token permission"
    assert "logs" not in jobs[0]
    assert classify_failure_signal(jobs)["category"] == "Authentication or permission gate"


def test_severity_repeated_default_branch_is_critical() -> None:
    failure = {"branch": "main", "default_branch": "main"}
    assert classify_ci_severity(failure) == "high"
    assert classify_ci_severity(failure, failure_streak=2) == "critical"
    assert classify_ci_severity({"branch": "feature", "default_branch": "main"}) == "low"


def test_grouping_and_incident_evidence_are_bounded() -> None:
    failures = [
        {"repo": "acme/api", "workflow": "CI", "branch": "main", "run_id": 2},
        {"repo": "acme/api", "workflow": "CI", "branch": "main", "run_id": 1},
    ]
    grouped = group_repeated_failures(failures)
    assert grouped[0]["count"] == 2

    normalized = normalise_workflow_run(_repo(), _run())
    failure = {
        **(normalized or {}),
        "failed_jobs": [{"name": "test", "failed_steps": []}],
        "commit_message": "x" * 10_000,
    }
    evidence = incident_evidence(failure)
    assert len(str(evidence)) <= MAX_EVIDENCE_CHARS + 100
    assert verify_incident_evidence(failure)
    assert build_incident_actions(failure)[0]["evidence_url"].startswith("https://")


def test_incident_investigation_drops_raw_logs() -> None:
    class Response:
        def json(self) -> dict:
            return {
                "jobs": [
                    {
                        "name": "test",
                        "conclusion": "failure",
                        "logs": "secret log body",
                        "steps": [{"name": "pytest", "conclusion": "failure"}],
                    }
                ]
            }

        def raise_for_status(self) -> None:
            return None

    class Client:
        async def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    import asyncio

    result = asyncio.run(
        investigate_workflow_run(
            Client(),
            {
                **(normalise_workflow_run(_repo(), _run()) or {}),
                "logs": "should not survive",
            },
        )
    )
    assert "logs" not in result
    assert "logs" not in result["failed_jobs"][0]
