from src.jobs.brief_intelligence import (
    brief_metadata,
    build_brief_signals,
    evidence_urls,
    prepare_brief_payload,
    render_fallback_brief,
    verify_action_candidate,
)


def _bundle() -> dict:
    return {
        "date": "2026-09-23T08:00:00+00:00",
        "work": {
            "ok": True,
            "data": {
                "priorities": [],
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Fix deploy",
                        "status": "blocked",
                        "blocked_reason": "GitHub token permission",
                    }
                ],
                "commitments": [],
            },
        },
        "calendar": {
            "ok": True,
            "data": [{"account": "default", "events": [{"summary": "Standup"}]}],
        },
        "gmail": {"ok": False, "error": "provider unavailable"},
        "github": {
            "ok": True,
            "data": [
                {
                    "repo": "acme/api",
                    "recent_failed_runs": [
                        {
                            "repo": "acme/api",
                            "severity": "critical",
                            "failure_signal": {"likely_cause": "main is red"},
                            "html_url": "https://github.com/acme/api/actions/runs/42",
                            "failed_jobs": [{"name": "test"}],
                        }
                    ],
                }
            ],
        },
        "granola": {"ok": True, "data": {"skipped": True}},
    }


def test_brief_prioritizes_ci_and_blocked_work_with_evidence() -> None:
    bundle = _bundle()
    signals = build_brief_signals(bundle)

    assert signals[0]["priority"] == "critical"
    assert signals[0]["source"] == "github"
    assert signals[1]["action"].startswith("Unblock task:")
    assert all(verify_action_candidate(signal) for signal in signals)
    assert evidence_urls(signals) == ["https://github.com/acme/api/actions/runs/42"]


def test_brief_payload_is_bounded_and_fallback_reports_source_health() -> None:
    bundle = _bundle()
    signals = build_brief_signals(bundle)
    payload = prepare_brief_payload(bundle | {"large": "x" * 100_000})
    fallback = render_fallback_brief(bundle, signals)

    assert len(payload) <= 24_000
    assert "Gmail source unavailable" in fallback
    assert len(fallback) <= 1_900
    metadata = brief_metadata(bundle, signals)
    assert metadata["action_count"] == len(signals)


def test_action_verifier_rejects_unsubstantiated_completed_write() -> None:
    assert not verify_action_candidate(
        {
            "source": "gmail",
            "reason": "inbox evidence",
            "action": "Email was sent",
            "confidence": "high",
        }
    )
