# CTO Agent

Slack DM → FastAPI → OpenRouter (Claude) → Postgres memory.

## Quick start (local)

1. Create a virtualenv and install deps:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements/dev.txt
   ```

2. Copy env and fill secrets (especially `DATABASE_URL`):

   ```bash
   cp .env.example .env
   ```

3. Apply the schema (safe if the Drizzle tables already exist):

   ```bash
   alembic upgrade head
   ```

4. Run the API:

   ```bash
   uvicorn src.main:app --reload --port 8000
   ```

5. Check health: `curl -s http://localhost:8000/healthz`

Slack Event Subscriptions URL: `https://<your-host>/slack/events`.

OpenAPI docs (`/docs`) are enabled in `development` and `test` only.

## Deploy (e.g. Coolify)

Use the repo **`Dockerfile`**: image runs `uvicorn src.main:app` and listens on **`PORT`** (default **8000**). Set environment variables in your platform (same keys as `.env.example`). Use a public **`APP_PUBLIC_URL`** for OpenRouter headers. Health check: **`GET /healthz`**. Slack **Request URL**: `https://<your-domain>/slack/events`.

On first deploy of a new database, run `alembic upgrade head`. An existing database from the previous Node/Drizzle app already has the same tables — stamp the revision if needed: `alembic stamp head`.

### Daily brief (GitHub Actions)

1. Set repo secrets: **`AGENT_BASE_URL`** (no trailing slash), e.g. `https://cto-agent.example.com`, and **`CRON_SECRET`** (same value as in production `CRON_SECRET`).
2. In production env, set **`GITHUB_BRIEF_REPOS`** to comma-separated `owner/repo` for PR/CI summary (optional but recommended).
3. Workflow [`.github/workflows/cron-daily-brief.yml`](.github/workflows/cron-daily-brief.yml) hits `POST /cron/daily-brief`; allow ~2 minutes for LLM + APIs (`--max-time 120`).

### Notion property names

Project database: **`Name`** (title), **`Status`** (status), **`Deadline`** (date), **`Priority`** (select, status, number, or text), **`Current focus`** (rich text), **`Next action`** (rich text). Names are defined in [`src/lib/notion_project_fields.py`](src/lib/notion_project_fields.py). Tasks database: **`Name`**, **`Due`**, **`Status`**, **`Project`** (relation).

### Granola

Tools call **`GET /meetings`**, **`GET /meetings/:id`**, **`GET /search`**. If your Granola API differs, change paths in [`src/tools/granola.py`](src/tools/granola.py) or set **`GRANOLA_API_BASE`** to the documented root.

## Scripts

| Command                                               | Description               |
| ----------------------------------------------------- | ------------------------- |
| `uvicorn src.main:app --reload --port 8000`           | Dev server                |
| `alembic upgrade head`                                | Apply migrations          |
| `pytest`                                              | Route and signature tests |
| `ruff check --fix src tests && ruff format src tests` | Lint / format             |
