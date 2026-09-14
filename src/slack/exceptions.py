from src.exceptions import DetailedHTTPException
from src.slack.constants import ErrorCode


class SlackUnauthorized(DetailedHTTPException):
    status_code = 401
    detail = ErrorCode.UNAUTHORIZED


class SlackBadRequest(DetailedHTTPException):
    status_code = 400
    detail = ErrorCode.BAD_REQUEST
