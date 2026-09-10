from pydantic import BaseModel


class CronHealthResponse(BaseModel):
    ok: bool
    cron: str


class CronDispatchResponse(BaseModel):
    ok: bool
    dispatched: bool
