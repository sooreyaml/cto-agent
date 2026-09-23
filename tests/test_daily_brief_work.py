import pytest
from src.jobs import daily_brief
from src.jobs.daily_brief import _work


@pytest.mark.asyncio
async def test_work_brief_uses_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_bundle():
        return {
            "priorities": [{"title": "Ship", "rank": 1}],
            "tasks": [{"title": "Fix CI", "status": "blocked"}],
            "commitments": [],
            "recent_decisions": [],
        }

    monkeypatch.setattr(daily_brief, "brief_bundle", fake_bundle)
    data = await _work()
    assert data["priorities"][0]["title"] == "Ship"
    assert data["tasks"][0]["status"] == "blocked"


def test_brief_prompt_has_no_notion() -> None:
    source = open(daily_brief.__file__, encoding="utf-8").read()
    assert "notion" not in source.lower()
    assert "Priorities" in source
    assert "Commitments" in source


@pytest.mark.asyncio
async def test_daily_brief_falls_back_and_audits_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = {
        "work": {
            "ok": True,
            "data": {
                "priorities": [],
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Fix deploy",
                        "status": "blocked",
                        "blocked_reason": "token permissions",
                    }
                ],
                "commitments": [],
            },
        },
        "calendar": {"ok": True, "data": []},
        "gmail": {"ok": False, "error": "unavailable"},
        "github": {"ok": True, "data": []},
        "granola": {"ok": True, "data": {"skipped": True}},
    }
    audit: dict[str, object] = {}
    sent: list[str] = []

    async def fake_safe(label: str, _fn) -> dict:
        return sources[label]

    async def fake_create(_owner: str, **kwargs: object) -> dict:
        audit["create"] = kwargs
        return {"id": "brief-1"}

    async def fake_finish(brief_id: str, **kwargs: object) -> dict:
        audit["finish"] = {"id": brief_id, **kwargs}
        return {"id": brief_id}

    async def fail_llm(**_kwargs: object) -> object:
        raise RuntimeError("provider unavailable")

    async def notify(message: str) -> None:
        sent.append(message)

    monkeypatch.setattr(daily_brief, "_safe", fake_safe)
    monkeypatch.setattr(daily_brief, "create_brief_run", fake_create)
    monkeypatch.setattr(daily_brief, "finish_brief_run", fake_finish)
    monkeypatch.setattr(daily_brief.llm.chat.completions, "create", fail_llm)
    monkeypatch.setattr(daily_brief, "notify_owner", notify)

    result = await daily_brief.run_daily_brief()

    assert result == {"signals": 1, "actions": 1, "render": "fallback", "delivery": "sent"}
    assert sent and "Unblock task: Fix deploy" in sent[0]
    assert audit["finish"] == {
        "id": "brief-1",
        "render_status": "fallback",
        "delivery_status": "sent",
        "error_type": "RuntimeError",
    }
