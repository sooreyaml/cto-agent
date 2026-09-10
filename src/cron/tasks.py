import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_running: set[str] = set()


def spawn_cron(name: str, fn: Callable[[], Awaitable[object]]) -> None:
    if name in _running:
        logger.info("cron job already running name=%s", name)
        return

    async def _run() -> None:
        _running.add(name)
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

    asyncio.create_task(_run(), name=f"cron-{name}")
