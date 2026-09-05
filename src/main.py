import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import get_settings
from src.cron.router import router as cron_router
from src.database import engine
from src.health.router import router as health_router
from src.memory import models as _memory_models  # noqa: F401
from src.slack.router import router as slack_router

settings = get_settings()
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("cto-agent")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("server starting env=%s", settings.NODE_ENV)
    yield
    await engine.dispose()


docs_on = settings.docs_enabled
app = FastAPI(
    title="CTO Agent",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json" if docs_on else None,
    docs_url="/docs" if docs_on else None,
    redoc_url="/redoc" if docs_on else None,
)

app.include_router(health_router)
app.include_router(slack_router)
app.include_router(cron_router)
