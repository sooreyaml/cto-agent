class ErrorCode:
    NOT_CONFIGURED = "Google OAuth is not configured"
    INVALID_TICKET = "Invalid or expired Google connect link"
    DENIED = "Google access was denied"
    NO_REFRESH_TOKEN = "Google did not return a refresh token"
    TOKEN_EXCHANGE_FAILED = "Google token exchange failed"


SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
)

TICKET_TTL_SECONDS = 20 * 60
CONNECT_COMMANDS = frozenset(
    {
        "connect google",
        "reconnect google",
        "link google",
        "google connect",
        "connect gmail",
        "reconnect gmail",
        "connect calendar",
        "link gmail",
    }
)
