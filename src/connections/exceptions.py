from src.exceptions import DetailedHTTPException


class ConnectOAuthNotConfigured(DetailedHTTPException):
    status_code = 503
    detail = "OAuth is not configured for this provider"


class ConnectOAuthInvalidTicket(DetailedHTTPException):
    status_code = 401
    detail = "Invalid or expired connect link"


class ConnectOAuthFailed(DetailedHTTPException):
    status_code = 400
    detail = "OAuth connect failed"
