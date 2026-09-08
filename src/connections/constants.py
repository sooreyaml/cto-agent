TICKET_TTL_SECONDS = 20 * 60

GITHUB_SCOPES = "repo read:user workflow"

GRANOLA_MCP_URL = "https://mcp.granola.ai/mcp"
GRANOLA_AUTH_ISSUER = "https://mcp-auth.granola.ai"
GRANOLA_AUTHORIZE = f"{GRANOLA_AUTH_ISSUER}/oauth2/authorize"
GRANOLA_TOKEN = f"{GRANOLA_AUTH_ISSUER}/oauth2/token"
GRANOLA_REGISTER = f"{GRANOLA_AUTH_ISSUER}/oauth2/register"
GRANOLA_SCOPES = "openid profile email offline_access"

_CONNECT_PREFIXES = ("please ", "can you ", "could you ", "hey ", "ok ")

GITHUB_CONNECT_COMMANDS = frozenset(
    {
        "connect github",
        "reconnect github",
        "link github",
        "github connect",
        "add github",
        "add github account",
    }
)

GRANOLA_CONNECT_COMMANDS = frozenset(
    {
        "connect granola",
        "reconnect granola",
        "link granola",
        "granola connect",
        "add granola",
        "add granola account",
    }
)

HIDDEN_EXTRA_KEYS = frozenset(
    {
        "refresh_token",
        "access_token",
        "client_secret",
        "code_verifier",
        "id_token",
        "client_id",
    }
)
