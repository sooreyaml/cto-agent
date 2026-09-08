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

Tokens are stored in Postgres. If you previously connected via Slack, the existing row is reused. If Google revokes access, the bot will ask you to connect again.

### Daily brief (GitHub Actions)

The brief is DMed on Discord. The cron endpoint runs the job **inline** (not in a background task) so a failed send fails the workflow.

1. Set repo secrets: **`AGENT_BASE_URL`** (no trailing slash), e.g. `https://cto-agent.example.com`, and **`CRON_SECRET`** (same value as in production `CRON_SECRET`).
2. In production env, set **`GITHUB_PAT`** (classic `repo` scope, or a fine-grained token on **All repositories**). The brief lists recently pushed repos the token can access (last 14 days, up to 10) and summarizes open PRs plus failing CI on each default branch.
3. Workflow [`.github/workflows/cron-daily-brief.yml`](.github/workflows/cron-daily-brief.yml) hits `POST /cron/daily-brief`; allow ~2 minutes for LLM + APIs (`--max-time 120`).
4. Confirm the API log shows `discord connected` after deploy. A brief cannot DM you if the Gateway bot is down.

### Notion property names

Project database: **`Name`** (title), **`Status`** (status), **`Deadline`** (date), **`Priority`** (select, status, number, or text), **`Current focus`** (rich text), **`Next action`** (rich text). Names are defined in [`src/lib/notion_project_fields.py`](src/lib/notion_project_fields.py). Tasks database: **`Name`**, **`Due`**, **`Status`**, **`Project`** (relation).

### Granola

Tools call **`GET /meetings`**, **`GET /meetings/:id`**, **`GET /search`**. If your Granola API differs, change paths in [`src/tools/granola.py`](src/tools/granola.py) or set **`GRANOLA_API_BASE`** to the documented root.

## Scripts

| Command                                               | Description                                      |
| ----------------------------------------------------- | ------------------------------------------------ |
| `docker compose up --build`                           | App + Postgres                                   |
| `uvicorn src.main:app --reload --port 8000`           | API only (needs local Postgres)                  |
| `alembic upgrade head`                                | Apply migrations (host / already run in compose) |
| `pytest`                                              | Route and signature tests                        |
| `ruff check --fix src tests && ruff format src tests` | Lint / format                                    |
