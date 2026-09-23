# CTO Agent

Discord and/or Slack DM → FastAPI → OpenRouter or ChatGPT/Codex OAuth → Postgres memory.

## Quick start

Compose starts **Postgres and the API** together. You do not need a separate Coolify/database resource.

1. Copy env and fill Discord and/or Slack / OpenRouter (or Codex) / other secrets:

   ```bash
   cp .env.example .env
   ```

2. Run:

   ```bash
   docker compose up --build
   ```

3. Check health: `curl -s http://localhost:8000/healthz`

The app container always uses `DATABASE_URL=postgresql://cto:…@db:5432/cto_agent` (the `db` service). That overrides any remote `DATABASE_URL` in `.env`.

Migrations run automatically before the API starts. The Docker entrypoint retries
transient database startup failures (12 attempts, 5 seconds apart by default) and
does not start Uvicorn if `alembic upgrade head` cannot complete. Override with
`MIGRATION_MAX_ATTEMPTS` and `MIGRATION_RETRY_SECONDS` when a managed database
needs a longer startup window. PostgreSQL advisory locking keeps concurrent app
replicas from running migrations at the same time.

Configure at least one chat surface:

- **Discord:** the API process opens a Gateway connection on startup. Logs should show `discord connected bot=… owner=…`.
- **Slack:** Event Subscriptions URL `https://<your-host>/slack/events`. Logs should show `slack events enabled path=/slack/events`.

OpenAPI docs (`/docs`) are enabled in `development` and `test` only.

## Deploy (Coolify)

1. Application type: **Docker Compose** (not a lone Dockerfile). Compose file: `docker-compose.yml`.
2. Expose the **`app`** service. Public port **8000**. Health check: **`GET /healthz`**.
3. Set the same secrets as `.env.example` (**Runtime only**, not build-time).
4. Set `POSTGRES_PASSWORD` to a strong value. You can **delete** any old remote `DATABASE_URL` — compose points the app at `db`.
5. Set `APP_PUBLIC_URL` to your public HTTPS origin (no trailing slash).
6. Set Discord (`DISCORD_BOT_TOKEN` + `DISCORD_USER_ID`) and/or Slack (`SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET` + `SLACK_USER_ID`).

### Discord

1. Create an application at the [Discord Developer Portal](https://discord.com/developers/applications).
2. **Bot** → Reset Token → `DISCORD_BOT_TOKEN`. Enable **Message Content Intent**.
3. Enable Developer Mode in Discord, right-click your user → Copy User ID → `DISCORD_USER_ID`.
4. **OAuth2 → URL Generator**: scope `bot`. Permissions: Send Messages, Read Message History, Attach Files, Add Reactions. Open the URL and add the bot to a private server you share with it (required before you can DM it).
5. Restart the API. DM the bot, or `@mention` it in a server channel. Only `DISCORD_USER_ID` is answered.

### Slack

1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps) (or reuse an existing one).
2. **OAuth & Permissions** bot scopes: `chat:write`, `files:read`, `users:read`, `reactions:write`, `im:history` (and `im:write` / `channels:history` as needed). Install to the workspace → `SLACK_BOT_TOKEN` (`xoxb-…`).
3. **Basic Information** → Signing Secret → `SLACK_SIGNING_SECRET`.
4. Your Slack member ID → `SLACK_USER_ID` (Profile → ⋯ → Copy member ID).
5. **Event Subscriptions** → Enable → Request URL `https://<your-domain>/slack/events`. Subscribe the bot to `message.im`.
6. Restart the API. DM the bot. Only `SLACK_USER_ID` is answered. Cron/notify DMs go to both Slack and Discord when both are configured.

### ChatGPT / Codex fallback (optional)

OpenRouter stays the primary model. After you connect ChatGPT, Codex OAuth is used only when OpenRouter fails (rate limit, timeout, 5xx, or billing). Same device-code login Hermes uses — not an OpenAI API key.

1. Keep `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` set. Leave `LLM_PROVIDER=openrouter`.
2. DM the bot `connect openai`. Open the link, sign in, enter the one-time code. Enable **Device code authorization** in ChatGPT → Settings → Security if it is rejected.
3. Wait for the “connected” DM (up to 15 minutes). Tokens live in Postgres and refresh automatically. This login is **separate** from the Codex CLI so they do not invalidate each other.
4. Optional: `CODEX_MODEL` (default `gpt-5.6-sol`) is the fallback model. Other ChatGPT OAuth options include `gpt-5.6-terra` and `gpt-5.6-luna`. Set `LLM_PROVIDER=openai-codex` only if you want Codex as the sole provider.

Local alternative: `python -m src.agent.codex_login` (needs Postgres). Plan quota still applies; this is not unlimited API.

### Google (Gmail + Calendar)

Do not paste a refresh token into env as the main setup. Connect from Discord or Slack after deploy.

1. In [Google Cloud Console](https://console.cloud.google.com/) create (or reuse) an OAuth **Web application** client. Enable **Gmail API** and **Google Calendar API**.
2. Add authorized redirect URI: `https://<your-domain>/auth/google/callback` (must match `APP_PUBLIC_URL`).
3. Consent screen: **Testing**, add your Google account as a test user. (Testing refresh tokens last 7 days — say `connect google` in Discord or Slack to refresh. Workspace **Internal** apps last longer.)
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. `GOOGLE_REFRESH_TOKEN` is optional leftover fallback.
5. DM the bot `connect google`, open the link, approve access (unverified-app warning is expected: Advanced → Go to … → Allow).
6. Say `connect google` again to add another account (work + personal). Google will ask which account. Optional: ask the agent to label it (`work`, `personal`) or set the default. Gmail/Calendar tools take an `account` email or label.

Tokens are stored in Postgres (one row per Google email). If Google revokes access, that account is dropped and the bot will ask you to connect again.

### Daily brief (GitHub Actions)

The brief is DMed on every configured surface (Discord and/or Slack). Cron routes return immediately and run the job in-process afterward so Cloudflare/Coolify cannot 504 a long brief. A job failure is logged and DMed; it does not fail the GitHub Action.

1. Set repo secrets: **`AGENT_BASE_URL`** (no trailing slash), e.g. `https://cto-agent.example.com`, and **`CRON_SECRET`** (same value as in production `CRON_SECRET`).
2. Connect GitHub from Discord (`connect github`) after setting **`GITHUB_CLIENT_ID`** and **`GITHUB_CLIENT_SECRET`** (GitHub OAuth App, callback `{APP_PUBLIC_URL}/auth/github/callback`). The brief lists recently pushed repos the token can access (last 14 days, up to 10) and summarizes open PRs plus failing CI on each default branch. `GITHUB_PAT` is optional leftover.
3. Workflow [`.github/workflows/cron-daily-brief.yml`](.github/workflows/cron-daily-brief.yml) hits `POST /cron/daily-brief` and retries transient proxy/network failures for up to three minutes. The actual brief continues in-process after the endpoint acknowledges it.
4. Confirm the API log shows `discord connected` and/or `slack events enabled` after deploy. A brief cannot DM you if no chat surface is up.

### Work board

Priorities, tasks, decisions, and commitments live in Postgres. The agent mutates them with `work_list` / `work_create` / `work_update`. At most five open priorities. The daily brief includes **Priorities**, **Tasks**, and **Commitments**.

Reminders: say when to nudge; `POST /cron/due` DMs due reminders and commitment `remind_at` times. CI watch: `POST /cron/watch` DMs new GitHub Actions failures on recently pushed repos.

Workflow [`.github/workflows/cron-due-watch.yml`](.github/workflows/cron-due-watch.yml) hits both endpoints every 15 minutes.

### Agent execution controller

Phase 3 adds a provider-neutral plan/execute/verify layer around the existing
OpenRouter and ChatGPT/Codex chat-completions loop. Explicitly complex requests
(for example, investigations, implementations, migrations, or multi-step work)
create an owner-scoped `agent_plans` record with a bounded objective, acceptance
criteria, workflow phases, and metadata-only tool evidence. The plan is marked
`planned`, `executing`, `verifying`, then `completed`, `blocked`, or `failed`.
Simple lookups keep the fast path and do not create a plan. The agent response
adds `planId` and `planStatus` only when a plan was created; provider selection
and existing tool handlers are unchanged.

### CTO intelligence layer

Phase 4 adds bounded, provider-neutral CTO intelligence on top of the existing
OpenRouter and ChatGPT/Codex loop:

- GitHub Actions watch polls recently active repositories, enriches only a small
  number of new failures with job and failed-step metadata, and stores owner-scoped
  CI incidents with severity, streak, evidence, and resolution state. A partial
  repository poll never resolves incidents. A GitHub 401 is handled as a
  reconnect condition instead of escaping as `Cron \`watch\` failed`.
- The daily brief ranks deterministic signals from CI, blocked/due work, calendar,
  and unread Gmail before asking the configured model to render the message. If
  the model is unavailable, a bounded evidence-linked fallback is delivered.
  Each attempt records source health, action/evidence counts, render status, and
  delivery status in `brief_runs`.
- `github_get_workflow_run` and `github_get_workflow_run_jobs` are read-only,
  bounded inspection tools. They expose metadata and failed step names, never raw
  logs or credentials.

The deployment entrypoint applies the Phase 4 schema automatically; for a manual
local run use `alembic upgrade head`. Existing provider selection, OAuth
connections, and tool handlers remain unchanged.

### GitHub

1. Create a GitHub OAuth App (Developer settings → OAuth Apps). Callback: `https://<your-domain>/auth/github/callback`.
2. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.
3. DM the bot `connect github`, open the link, approve access.

The user token is stored in Postgres. Scopes: `repo`, `read:user`, `workflow`.

### Granola

DM the bot `connect granola` and sign in in the browser. Granola MCP uses OAuth with dynamic client registration — no API key and no extra env vars. Tools list, fetch, and search meetings through MCP. Optional leftover: `GRANOLA_API_KEY` / `GRANOLA_API_BASE` if you still want the REST API as a fallback.

## Scripts

| Command                                               | Description                                                |
| ----------------------------------------------------- | ---------------------------------------------------------- |
| `docker compose up --build`                           | App + Postgres                                             |
| `uvicorn src.main:app --reload --port 8000`           | API only (needs local Postgres)                            |
| `alembic upgrade head`                                | Apply migrations (host / already run in compose)           |
| `python -m src.agent.codex_login`                     | ChatGPT / Codex device-code login (or DM `connect openai`) |
| `ruff check --fix src tests && ruff format src tests` | Lint / format                                              |
