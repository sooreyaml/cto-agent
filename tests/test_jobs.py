from src.jobs.due import format_due_message
from src.jobs.watch import failure_cursor_id, format_watch_message


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
