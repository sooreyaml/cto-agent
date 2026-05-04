# CTO Agent

Slack DM → Hono → OpenRouter (Claude) → Postgres memory. See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for the full plan.

## Quick start

1. Copy env and fill secrets:

   ```bash
   cp .env.example .env
   ```

2. Start Postgres (local):

   ```bash
   docker compose up -d postgres
   ```

3. Push schema:

   ```bash
   pnpm drizzle:push
   ```

4. Run the API:

   ```bash
   pnpm dev
   ```

5. Check health: `curl -s http://localhost:3000/healthz`

Slack Event Subscriptions URL: `https://<your-host>/slack/events`.

## Scripts

| Script            | Description        |
| ----------------- | ------------------ |
| `pnpm dev`        | Watch mode (tsx)   |
| `pnpm build`      | Compile to `dist/` |
| `pnpm start`      | Run compiled app   |
| `pnpm drizzle:push` | Apply schema to DB |
