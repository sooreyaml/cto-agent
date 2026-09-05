from src.exceptions import DetailedHTTPException
from src.google.constants import ErrorCode


class GoogleOAuthNotConfigured(DetailedHTTPException):
    status_code = 503
    detail = ErrorCode.NOT_CONFIGURED


class GoogleOAuthInvalidTicket(DetailedHTTPException):
    status_code = 401
    detail = ErrorCode.INVALID_TICKET


class GoogleOAuthDenied(DetailedHTTPException):
    status_code = 400
    detail = ErrorCode.DENIED
