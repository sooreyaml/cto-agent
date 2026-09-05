from fastapi import HTTPException


class DetailedHTTPException(HTTPException):
    status_code: int = 500
    detail: str = "server_error"
    headers: dict[str, str] | None = None

    def __init__(self) -> None:
        super().__init__(
            status_code=self.status_code,
            detail=self.detail,
            headers=self.headers,
        )


class ConfigError(Exception):
    pass
