import logging

from src.work.mapping import format_work_snapshot
from src.work.repository import snapshot_rows

logger = logging.getLogger(__name__)


async def load_work_snapshot() -> str:
    try:
        rows = await snapshot_rows()
    except Exception:
        logger.exception("work snapshot failed")
        return "Work board unavailable."
    return format_work_snapshot(
        priorities=rows["priorities"],
        tasks=rows["tasks"],
        commitments=rows["commitments"],
    )
