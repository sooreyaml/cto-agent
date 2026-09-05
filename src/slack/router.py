import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from src.slack.client import verify_slack_signature
from src.slack.dedupe import is_duplicate_slack_event
from src.slack.exceptions import SlackBadRequest, SlackUnauthorized
from src.slack.schemas import SlackCallbackBody
from src.slack.service import dispatch_detached, handle_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/slack", tags=["slack"])


@router.post(
    "/events",
    response_model=None,
    summary="Slack Events API",
    description=(
        "Verifies the Slack signature, answers url_verification, "
        "dedupes event_id, then handles DMs in the background."
    ),
    responses={
        401: {"description": "Invalid Slack signature"},
        400: {"description": "Body is not JSON"},
    },
)
async def slack_events(request: Request) -> PlainTextResponse | JSONResponse:
    raw_body = (await request.body()).decode("utf-8")
    timestamp = request.headers.get("x-slack-request-timestamp")
    signature = request.headers.get("x-slack-signature")
    valid, reason = verify_slack_signature(raw_body, timestamp, signature)
    if not valid:
        logger.warning("invalid slack signature reason=%s", reason)
        raise SlackUnauthorized()

    try:
        payload = json.loads(raw_body)
        body = SlackCallbackBody.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SlackBadRequest() from exc

    if body.type == "url_verification":
        return JSONResponse({"challenge": body.challenge})

    if body.type == "event_callback" and body.event_id:
        if is_duplicate_slack_event(body.event_id):
            return PlainTextResponse("OK")

    dispatch_detached("slack-event", lambda: handle_event(body))
    return PlainTextResponse("OK")
