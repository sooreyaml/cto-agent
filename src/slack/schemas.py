from pydantic import BaseModel, ConfigDict


class SlackUrlVerificationResponse(BaseModel):
    challenge: str | None = None


class SlackFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mimetype: str | None = None
    url_private: str | None = None
    url_private_download: str | None = None


class SlackEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    channel: str | None = None
    user: str | None = None
    text: str | None = None
    ts: str | None = None
    thread_ts: str | None = None
    bot_id: str | None = None
    subtype: str | None = None
    channel_type: str | None = None
    files: list[SlackFile] | None = None


class SlackCallbackBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    challenge: str | None = None
    event_id: str | None = None
    event: SlackEvent | None = None
    team_id: str | None = None
    api_app_id: str | None = None
