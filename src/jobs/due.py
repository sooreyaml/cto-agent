import logging

from src.notify import notify_owner
from src.work.repository import due_items, mark_reminders_sent

logger = logging.getLogger(__name__)


def format_due_message(bundle: dict) -> str | None:
    lines: list[str] = []
    for reminder in bundle.get("reminders") or []:
        lines.append(f"- {reminder.get('message')}")
    for commitment in bundle.get("commitments") or []:
        who = commitment.get("who") or "me"
        what = commitment.get("what")
        due = (commitment.get("due_at") or "")[:10]
        suffix = f" (due {due})" if due else ""
        lines.append(f"- {who}: {what}{suffix}")
    if not lines:
        return None
    return "**Reminders**\n" + "\n".join(lines)


async def run_due() -> dict[str, int]:
    bundle = await due_items()
    text = format_due_message(bundle)
    reminder_ids = [item["id"] for item in bundle.get("reminders") or []]
    commitment_ids = [item["id"] for item in bundle.get("commitments") or []]
    if text:
        await notify_owner(text)
        await mark_reminders_sent(reminder_ids, commitment_ids)
        logger.info(
            "due reminders sent reminders=%s commitments=%s",
            len(reminder_ids),
            len(commitment_ids),
        )
    return {"reminders": len(reminder_ids), "commitments": len(commitment_ids)}
