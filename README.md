# CTO Agent

Discord DM → FastAPI → OpenRouter (Claude) → Postgres memory.

## Quick start

Compose starts **Postgres and the API** together. You do not need a separate Coolify/database resource.

1. Copy env and fill Discord / OpenRouter / other secrets:

   ```bash
   cp .env.example .env
   ```

2. Run:

   ```bash
   docker compose up --build
   ```

3. Check health: `curl -s http://localhost:8000/healthz`

The app container always uses `DATABASE_URL=postgresql://cto:…@db:5432/cto_agent` (the `db` service). That overrides any remote `DATABASE_URL` in `.env`.

Migrations run automatically on container start (`alembic upgrade head`).

Discord does not use an HTTP events URL. The API process opens a Gateway connection on startup. Logs should show `discord connected bot=… owner=…`.

OpenAPI docs (`/docs`) are enabled in `development` and `test` only.

## Deploy (Coolify)

1. Application type: **Docker Compose** (not a lone Dockerfile). Compose file: `docker-compose.yml`.
2. Expose the **`app`** service. Public port **8000**. Health check: **`GET /healthz`**.
3. Set the same secrets as `.env.example` (**Runtime only**, not build-time).
4. Set `POSTGRES_PASSWORD` to a strong value. You can **delete** any old remote `DATABASE_URL` — compose points the app at `db`.
5. Set `APP_PUBLIC_URL` to your public HTTPS origin (no trailing slash).
6. Set `DISCORD_BOT_TOKEN` and `DISCORD_USER_ID`. Slack env vars are unused and can be deleted.

### Discord

1. Create an application at the [Discord Developer Portal](https://discord.com/developers/applications).
2. **Bot** → Reset Token → `DISCORD_BOT_TOKEN`. Enable **Message Content Intent**.
3. Enable Developer Mode in Discord, right-click your user → Copy User ID → `DISCORD_USER_ID`.
4. **OAuth2 → URL Generator**: scope `bot`. Permissions: Send Messages, Read Message History, Attach Files, Add Reactions. Open the URL and add the bot to a private server you share with it (required before you can DM it).
5. Restart the API. DM the bot, or `@mention` it in a server channel. Only `DISCORD_USER_ID` is answered.

### Google (Gmail + Calendar)

Do not paste a refresh token into env as the main setup. Connect from Discord after deploy.

1. In [Google Cloud Console](https://console.cloud.google.com/) create (or reuse) an OAuth **Web application** client. Enable **Gmail API** and **Google Calendar API**.
2. Add authorized redirect URI: `https://<your-domain>/auth/google/callback` (must match `APP_PUBLIC_URL`).
3. Consent screen: **Testing**, add your Google account as a test user. (Testing refresh tokens last 7 days — say `connect google` in Discord to refresh. Workspace **Internal** apps last longer.)
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. `GOOGLE_REFRESH_TOKEN` is optional leftover fallback.
5. DM the bot `connect google`, open the link, approve access (unverified-app warning is expected: Advanced → Go to … → Allow).
6. Say `connect google` again to add another account (work + personal). Google will ask which account. Optional: ask the agent to label it (`work`, `personal`) or set the default. Gmail/Calendar tools take an `account` email or label.

Tokens are stored in Postgres (one row per Google email). If Google revokes access, that account is dropped and the bot will ask you to connect again.

### Daily brief (GitHub Actions)

The brief is DMed on Discord. Cron routes return immediately and run the job in-process afterward so Cloudflare/Coolify cannot 504 a long brief. A job failure is logged and DMed; it does not fail the GitHub Action.

1. Set repo secrets: **`AGENT_BASE_URL`** (no trailing slash), e.g. `https://cto-agent.example.com`, and **`CRON_SECRET`** (same value as in production `CRON_SECRET`).
2. Connect GitHub from Discord (`connect github`) after setting **`GITHUB_CLIENT_ID`** and **`GITHUB_CLIENT_SECRET`** (GitHub OAuth App, callback `{APP_PUBLIC_URL}/auth/github/callback`). The brief lists recently pushed repos the token can access (last 14 days, up to 10) and summarizes open PRs plus failing CI on each default branch. `GITHUB_PAT` is optional leftover.
3. Workflow [`.github/workflows/cron-daily-brief.yml`](.github/workflows/cron-daily-brief.yml) hits `POST /cron/daily-brief`; allow ~2 minutes for LLM + APIs (`--max-time 120`).
4. Confirm the API log shows `discord connected` after deploy. A brief cannot DM you if the Gateway bot is down.

### Work board

Priorities, tasks, decisions, and commitments live in Postgres. The agent mutates them with `work_list` / `work_create` / `work_update`. At most five open priorities. The daily brief includes **Priorities**, **Tasks**, and **Commitments**.

Reminders: say when to nudge; `POST /cron/due` DMs due reminders and commitment `remind_at` times. CI watch: `POST /cron/watch` DMs new GitHub Actions failures on recently pushed repos.

Workflow [`.github/workflows/cron-due-watch.yml`](.github/workflows/cron-due-watch.yml) hits both endpoints every 15 minutes.

### GitHub

1. Create a GitHub OAuth App (Developer settings → OAuth Apps). Callback: `https://<your-domain>/auth/github/callback`.
2. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.
3. DM the bot `connect github`, open the link, approve access.

The user token is stored in Postgres. Scopes: `repo`, `read:user`, `workflow`.

### Granola

DM the bot `connect granola` and sign in in the browser. Granola MCP uses OAuth with dynamic client registration — no API key and no extra env vars. Tools list, fetch, and search meetings through MCP. Optional leftover: `GRANOLA_API_KEY` / `GRANOLA_API_BASE` if you still want the REST API as a fallback.

## Scripts

| Command                                               | Description                                      |
| ----------------------------------------------------- | ------------------------------------------------ |
| `docker compose up --build`                           | App + Postgres                                   |
| `uvicorn src.main:app --reload --port 8000`           | API only (needs local Postgres)                  |
| `alembic upgrade head`                                | Apply migrations (host / already run in compose) |
| `pytest`                                              | Route and signature tests                        |
| `ruff check --fix src tests && ruff format src tests` | Lint / format                                    |
