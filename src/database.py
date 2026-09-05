import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

engine = create_async_engine(settings.async_database_url, pool_size=10, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

T = TypeVar("T")
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _main_loop
    _main_loop = loop


def run_from_thread(coro: Coroutine[object, object, T], timeout: float = 15) -> T:
    loop = _main_loop
    if loop is not None and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)
    return asyncio.run(coro)


def database_target() -> str:
    parsed = make_url(settings.async_database_url)
    host = parsed.host or "localhost"
    port = parsed.port or 5432
    name = parsed.database or "?"
    return f"{host}:{port}/{name}"


async def ping_db() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def get_async_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
        await session.commit()
