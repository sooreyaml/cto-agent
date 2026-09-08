import pytest
from pydantic import ValidationError
from src.agent.prompt import build_system_prompt
from src.config import Settings
from src.discord.format import slack_mrkdwn_to_discord, split_discord_sections


def test_converts_links_bold_and_italic() -> None:
    src = "*Today* _focus_ <https://example.com|Calendar> and <https://x.test>"
    assert slack_mrkdwn_to_discord(src) == (
        "**Today** *focus* [Calendar](https://example.com) and https://x.test"
    )


def test_leaves_code_spans_alone() -> None:
    src = "use `*not-bold*` and ```\n*still*\n```"
    assert slack_mrkdwn_to_discord(src) == src


def test_splits_long_messages() -> None:
    body = "alpha\n\n" + ("b" * 1990) + "\n\ncharlie"
    parts = split_discord_sections(body, max_len=2000)
    assert len(parts) == 2
    assert all(len(part) <= 2000 for part in parts)
    assert parts[0].startswith("alpha")
    assert parts[1] == "charlie"


def test_system_prompt_is_discord() -> None:
    prompt = build_system_prompt(work_context="Work board:\n- P1: Ship")
    assert "Discord" in prompt
    assert "Slack mrkdwn" not in prompt
    assert "Notion" not in prompt
    assert "P1: Ship" in prompt
    assert "work_list" in prompt or "Work:" in prompt


def test_discord_user_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    monkeypatch.setenv("DISCORD_USER_ID", "")
    with pytest.raises(ValidationError):
        Settings()
