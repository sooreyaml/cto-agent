from pydantic import BaseModel


class CronHealthResponse(BaseModel):
    ok: bool
    cron: str


class DailyBriefResponse(BaseModel):
    ok: bool
    dispatched: bool
