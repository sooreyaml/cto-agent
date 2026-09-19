import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_running: set[str] = set()
_tasks: set[asyncio.Task[None]] = set()


def spawn_cron(name: str, fn: Callable[[], Awaitable[object]]) -> None:
    if name in _running:
        logger.info("cron job already running name=%s", name)
        return
    _running.add(name)

    async def _run() -> None:
        try:
            await fn()
        except Exception:
            logger.exception("cron job failed name=%s", name)
            try:
                from src.notify import notify_owner

                await notify_owner(f"Cron `{name}` failed. Check API logs.")
            except Exception:
                logger.exception("cron failure notify failed name=%s", name)
        finally:
            _running.discard(name)

    try:
        task = asyncio.create_task(_run(), name=f"cron-{name}")
    except Exception:
        _running.discard(name)
        raise
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
