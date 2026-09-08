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
