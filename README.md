# CTO Agent

Slack DM → Hono → OpenRouter (Claude) → Postgres memory. See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for the full plan.

## Quick start (local)

1. Copy env and fill secrets (especially `DATABASE_URL` for your **hosted** Postgres):

   ```bash
   cp .env.example .env
   ```

2. Apply the schema to that database:

   ```bash
   pnpm drizzle:push
   ```

3. Run the API:

   ```bash
   pnpm dev
   ```

   Or production-style:

   ```bash
   pnpm build && pnpm start
   ```

4. Check health: `curl -s http://localhost:3000/healthz`

Slack Event Subscriptions URL: `https://<your-host>/slack/events`.

## Deploy (e.g. Coolify)

Use the repo **`Dockerfile`**: image runs `node dist/index.js` and listens on **`PORT`** (default **3000**). Set environment variables in your platform (same keys as `.env.example`). Use a public **`APP_PUBLIC_URL`** for OpenRouter headers. Health check: **`GET /healthz`**. Slack **Request URL**: `https://<your-domain>/slack/events`.

### Daily brief (GitHub Actions)

1. Set repo secrets: **`AGENT_BASE_URL`** (no trailing slash), e.g. `https://cto-agent.example.com`, and **`CRON_SECRET`** (same value as in production `CRON_SECRET`).
2. In production env, set **`GITHUB_BRIEF_REPOS`** to comma-separated `owner/repo` for PR/CI summary (optional but recommended).
3. Workflow [`.github/workflows/cron-daily-brief.yml`](./.github/workflows/cron-daily-brief.yml) hits `POST /cron/daily-brief`; allow ~2 minutes for LLM + APIs (`--max-time 120`).

### Notion property names

Project database: **`Name`** (title), **`Status`** (status), **`Deadline`** (date), **`Priority`** (select, status, number, or text), **`Current focus`** (rich text), **`Next action`** (rich text). Names are defined in [`src/lib/notion-project-fields.ts`](./src/lib/notion-project-fields.ts). Tasks database: **`Name`**, **`Due`**, **`Status`**, **`Project`** (relation).

### Granola

Tools call **`GET /meetings`**, **`GET /meetings/:id`**, **`GET /search`**. If your Granola API differs, change paths in [`src/tools/granola.ts`](./src/tools/granola.ts) or set **`GRANOLA_API_BASE`** to the documented root.

## Scripts

| Script            | Description        |
| ----------------- | ------------------ |
| `pnpm dev`        | Watch mode (tsx)   |
| `pnpm build`      | Compile to `dist/` |
| `pnpm start`      | Run compiled app   |
| `pnpm drizzle:push` | Apply schema to DB |
