from src.cron.constants import ErrorCode
from src.exceptions import DetailedHTTPException


class CronUnauthorized(DetailedHTTPException):
    status_code = 401
    detail = ErrorCode.UNAUTHORIZED


class CronNotConfigured(DetailedHTTPException):
    status_code = 503
    detail = ErrorCode.CRON_SECRET_NOT_CONFIGURED
