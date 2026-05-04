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

## Scripts

| Script            | Description        |
| ----------------- | ------------------ |
| `pnpm dev`        | Watch mode (tsx)   |
| `pnpm build`      | Compile to `dist/` |
| `pnpm start`      | Run compiled app   |
| `pnpm drizzle:push` | Apply schema to DB |
