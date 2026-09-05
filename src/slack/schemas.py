from pydantic import BaseModel, Field


class SlackUrlVerificationResponse(BaseModel):
    challenge: str | None = None


class SlackFile(BaseModel):
    mimetype: str | None = None
    url_private: str | None = None
    url_private_download: str | None = None


class SlackEvent(BaseModel):
    type: str | None = None
    channel: str | None = None
    user: str | None = None
    text: str | None = None
    ts: str | None = None
    thread_ts: str | None = None
    bot_id: str | None = None
    subtype: str | None = None
    channel_type: str | None = None
    files: list[SlackFile] = Field(default_factory=list)


class SlackCallbackBody(BaseModel):
    type: str | None = None
    challenge: str | None = None
    event_id: str | None = None
    event: SlackEvent | None = None
