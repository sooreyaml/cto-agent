from typing import Any

Provider = dict[str, Any]

PROVIDERS: dict[str, Provider] = {
    "github": {
        "name": "GitHub",
        "base_url": "https://api.github.com",
        "auth": "oauth",
        "how": "Say “connect github” in Discord and sign in. Needs a GitHub OAuth App once (GITHUB_CLIENT_ID + SECRET), same idea as Google.",
        "extra": ["username"],
    },
    "granola": {
        "name": "Granola",
        "base_url": "https://mcp.granola.ai",
        "auth": "oauth",
        "how": "Say “connect granola” in Discord and sign in in the browser. No API key and no extra env.",
        "extra": [],
    },
    "linear": {
        "name": "Linear",
        "base_url": "https://api.linear.app",
        "auth": "bearer",
        "how": "Linear → Settings → API → Personal API key.",
        "extra": [],
    },
    "sentry": {
        "name": "Sentry",
        "base_url": "https://sentry.io/api/0",
        "auth": "bearer",
        "how": "Sentry → Settings → Auth Tokens (org read + event read).",
        "extra": ["org"],
    },
    "vercel": {
        "name": "Vercel",
        "base_url": "https://api.vercel.com",
        "auth": "bearer",
        "how": "Vercel → Account Settings → Tokens.",
        "extra": ["team_id"],
    },
    "coolify": {
        "name": "Coolify",
        "base_url": None,
        "auth": "bearer",
        "how": "Coolify → Keys & Tokens. Also send base_url like https://coolify.example.com/api/v1",
        "extra": ["base_url"],
        "requires_base_url": True,
    },
    "tavily": {
        "name": "Tavily Search",
        "base_url": "https://api.tavily.com",
        "auth": "bearer",
        "how": "tavily.com → API key.",
        "extra": [],
    },
    "stripe": {
        "name": "Stripe",
        "base_url": "https://api.stripe.com",
        "auth": "bearer",
        "how": "Stripe → Developers → Restricted key (read only).",
        "extra": [],
    },
    "cloudflare": {
        "name": "Cloudflare",
        "base_url": "https://api.cloudflare.com/client/v4",
        "auth": "bearer",
        "how": "Cloudflare → My Profile → API Tokens.",
        "extra": [],
    },
    "notion": {
        "name": "Notion",
        "base_url": "https://api.notion.com",
        "auth": "bearer",
        "how": "notion.so/my-integrations → New integration → copy the token. Share the pages/DBs with it.",
        "extra": [],
        "headers": {"Notion-Version": "2022-06-28"},
    },
    "slack": {
        "name": "Slack",
        "base_url": "https://slack.com/api",
        "auth": "bearer",
        "how": "Slack app → OAuth → Bot User OAuth Token (xoxb-…).",
        "extra": [],
    },
}


def normalize_provider(raw: object) -> str:
    return str(raw or "").strip().lower().replace(" ", "_")


def get_provider(name: str) -> Provider:
    key = normalize_provider(name)
    spec = PROVIDERS.get(key)
    if spec is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"Unknown provider {name!r}. Known: {known}")
    return spec


def catalog_public() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "name": spec["name"],
            "auth": spec.get("auth") or "bearer",
            "how": spec["how"],
            "needs_base_url": bool(spec.get("requires_base_url")),
            "extra": list(spec.get("extra") or []),
        }
        for key, spec in PROVIDERS.items()
    ]
