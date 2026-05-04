# CTO Agent: Development and Implementation

**Owner:** Sooreoluwa
**Stack:** TypeScript, Hono, OpenAI SDK pointed at OpenRouter, Postgres + Drizzle, Slack Web API, self-hosted Docker Compose, GitHub Actions cron
**Brain:** Claude Sonnet 4.6 via OpenRouter
**Deploy target:** Your VPS (automation.yamlgroup.tech subdomain or new one)

---

## 1. The Flow End to End

### Conversational path (you DM the bot)

```
Slack DM
  ↓ POST /slack/events
Hono server
  ↓ verify X-Slack-Signature (HMAC-SHA256, 5-min replay window)
  ↓ respond 200 immediately
  ↓ dedupe: if event_callback and event_id already seen → OK and return (Slack retries)
  ↓ dispatch async via dispatchDetached() — do not use executionCtx.waitUntil (Workers-only)
Async handler
  ↓ react :eyes: on the user message
  ↓ load last 12 turns from Postgres for this channel_id
  ↓ build messages array: [system, ...history, user]
Agent Loop (max 10 iterations)
  ↓ OpenAI SDK call to OpenRouter
  ↓ model: anthropic/claude-sonnet-4.6
  ↓ tools: full registry (23 functions)
  ├─ if response.tool_calls.length === 0 → break, this is the final answer
  └─ else: execute each tool_call, append role:tool messages, loop again
  ↓ post final text to Slack DM
  ↓ react :white_check_mark: on the user message
  ↓ persist conversation turn + log row to Postgres
```

### Daily brief path

```
GitHub Actions cron (0 7 * * 1-5)
  ↓ curl POST /cron/daily-brief with Authorization: Bearer ${CRON_SECRET}
Hono server
  ↓ verify cron secret
  ↓ run brief job
Brief job
  ↓ Promise.all([notion projects, calendar today, gmail unread, github prs])
  ↓ compose via Sonnet 4.6 (single non-tool LLM call)
  ↓ post to Slack DM (your user ID)
  ↓ log to Postgres
```

The two paths share: LLM client, Slack client, Postgres connection, error handling, logging. Different entry points, same internals.

---

## 2. Tech Stack and Why

| Layer | Choice | Why |
|---|---|---|
| Runtime | Node 22 (TypeScript) | OpenAI SDK is JS-first, modern types |
| Server | Hono | Lightweight, modern, sub-millisecond routing, works on any runtime |
| LLM client | `openai` package, baseURL = openrouter.ai/api/v1 | OpenRouter speaks OpenAI's spec, you switch models without rewriting |
| Memory | Postgres + Drizzle | Type-safe SQL, migrations, real persistence, survives restarts |
| Slack | `@slack/web-api` + raw signature verify | Official client for Web API, raw crypto for signature |
| Notion | `@notionhq/client` | Official |
| Google | `googleapis` | Official, covers Gmail and Calendar |
| GitHub | `octokit` | Official |
| Validation | `zod` | Tool input parsing, env validation |
| Cron | GitHub Actions + endpoint | Free, no extra infra, version-controlled schedule |
| Container | Docker (`Dockerfile`) | Portable image; deploy via Coolify, raw Docker, or your orchestrator |
| Reverse proxy / TLS | Host platform (e.g. Coolify, Traefik, Caddy) | Not defined in this repo; use what your VPS/PaaS provides |

---

## 3. Project Structure

```
cto-agent/
├── src/
│   ├── index.ts                       # Hono app entry
│   ├── config.ts                      # env vars (zod-validated)
│   ├── routes/
│   │   ├── slack.ts                   # /slack/events webhook
│   │   ├── cron.ts                    # /cron/daily-brief, /cron/health
│   │   └── health.ts                  # /healthz
│   ├── agent/
│   │   ├── loop.ts                    # the tool-calling loop
│   │   ├── llm.ts                     # OpenAI SDK client (OpenRouter)
│   │   ├── prompt.ts                  # system prompt builder
│   │   └── registry.ts                # tool registry: name → handler + schema
│   ├── tools/
│   │   ├── notion.ts                  # 6 tools
│   │   ├── gmail.ts                   # 4 tools
│   │   ├── calendar.ts                # 5 tools
│   │   ├── github.ts                  # 5 tools
│   │   └── granola.ts                 # 3 tools (optional)
│   ├── memory/
│   │   ├── db.ts                      # Drizzle client
│   │   ├── schema.ts                  # Drizzle schema
│   │   └── repository.ts              # CRUD helpers
│   ├── integrations/
│   │   ├── slack.ts                   # Web API + signature verify
│   │   ├── slack-dedupe.ts            # event_id dedupe (in-proc; DB if multi-instance)
│   │   ├── google.ts                  # OAuth2 client factory
│   │   ├── notion.ts                  # client factory
│   │   ├── github.ts                  # Octokit factory
│   │   └── granola.ts                 # HTTP client
│   ├── jobs/
│   │   └── daily-brief.ts
│   └── utils/
│       ├── logger.ts                  # pino
│       ├── dispatch.ts                # background work on Node (replaces Workers waitUntil)
│       └── errors.ts
├── drizzle/
│   └── migrations/
├── .github/
│   └── workflows/
│       ├── cron-daily-brief.yml
│       └── deploy.yml
├── .env.example
├── drizzle.config.ts
├── package.json
├── tsconfig.json
├── Dockerfile
└── README.md
```

---

## 4. Environment Variables

`.env` example (also commit `.env.example` with empty values):

```bash
# Server
PORT=3000
NODE_ENV=production
LOG_LEVEL=info
TIMEZONE=Europe/London

# Postgres
DATABASE_URL=postgres://cto:cto@localhost:5432/cto_agent

# OpenRouter
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=anthropic/claude-sonnet-4.6
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_USER_ID=U...

# Notion
NOTION_TOKEN=ntn_...
NOTION_PROJECTS_DB_ID=...
NOTION_TASKS_DB_ID=...
NOTION_LOGS_DB_ID=...

# Google (single OAuth app for Gmail + Calendar)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
GOOGLE_USER_EMAIL=goodnessolawale@gmail.com

# GitHub
GITHUB_PAT=ghp_...
GITHUB_USERNAME=goodnessolawale

# Granola (optional)
GRANOLA_API_BASE=https://api.granola.ai
GRANOLA_API_KEY=

# Cron auth
CRON_SECRET=... # generate via openssl rand -hex 32
```

---

## 5. Database Schema (Drizzle)

`src/memory/schema.ts`:

```ts
import {
  pgTable, uuid, text, jsonb, timestamp, integer, boolean
} from "drizzle-orm/pg-core";

export const conversations = pgTable("conversations", {
  id: uuid("id").primaryKey().defaultRandom(),
  channelId: text("channel_id").notNull().unique(),
  slackUserId: text("slack_user_id").notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  lastActiveAt: timestamp("last_active_at").defaultNow().notNull(),
});

export const messages = pgTable("messages", {
  id: uuid("id").primaryKey().defaultRandom(),
  conversationId: uuid("conversation_id")
    .references(() => conversations.id, { onDelete: "cascade" })
    .notNull(),
  role: text("role").notNull(), // 'system' | 'user' | 'assistant' | 'tool'
  content: text("content"),
  toolCalls: jsonb("tool_calls"),       // when role='assistant'
  toolCallId: text("tool_call_id"),     // when role='tool'
  toolName: text("tool_name"),          // when role='tool'
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const logs = pgTable("logs", {
  id: uuid("id").primaryKey().defaultRandom(),
  channelId: text("channel_id"),
  slackUserId: text("slack_user_id"),
  userMessage: text("user_message"),
  agentOutput: text("agent_output"),
  toolsCalled: jsonb("tools_called"),
  iterations: integer("iterations"),
  latencyMs: integer("latency_ms"),
  inputTokens: integer("input_tokens"),
  outputTokens: integer("output_tokens"),
  costUsd: text("cost_usd"),            // store as decimal string
  success: boolean("success").default(true).notNull(),
  errorMessage: text("error_message"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});
```

Memory window: pull last N messages per conversation by `created_at DESC LIMIT 24`, reverse, replay into the next LLM call.

---

## 6. Critical Code Snippets

### 6.1 LLM client (`src/agent/llm.ts`)

```ts
import OpenAI from "openai";
import { config } from "../config";

export const llm = new OpenAI({
  baseURL: config.OPENROUTER_BASE_URL,
  apiKey: config.OPENROUTER_API_KEY,
  defaultHeaders: {
    "HTTP-Referer": "https://your-vps-domain.com",
    "X-Title": "CTO Agent",
  },
});

export const MODEL = config.OPENROUTER_MODEL;
```

### 6.2 Agent loop (`src/agent/loop.ts`)

```ts
import { llm, MODEL } from "./llm";
import { buildSystemPrompt } from "./prompt";
import { toolRegistry, toolSpecs } from "./registry";
import { loadHistory, persistTurn } from "../memory/repository";
import { logger } from "../utils/logger";

type AgentInput = {
  channelId: string;
  slackUserId: string;
  userMessage: string;
};

const MAX_ITERATIONS = 10;

export async function runAgent(input: AgentInput) {
  const startedAt = Date.now();
  const toolsUsed: string[] = [];
  let inputTokens = 0;
  let outputTokens = 0;

  const history = await loadHistory(input.channelId, 24);
  const messages: any[] = [
    { role: "system", content: buildSystemPrompt() },
    ...history,
    { role: "user", content: input.userMessage },
  ];

  let finalText = "";
  let iterations = 0;

  for (let i = 0; i < MAX_ITERATIONS; i++) {
    iterations++;
    const response = await llm.chat.completions.create({
      model: MODEL,
      messages,
      tools: toolSpecs,
      tool_choice: "auto",
      temperature: 0.3,
      max_tokens: 2048,
    });

    inputTokens += response.usage?.prompt_tokens ?? 0;
    outputTokens += response.usage?.completion_tokens ?? 0;

    const msg = response.choices[0].message;
    messages.push(msg);

    if (!msg.tool_calls || msg.tool_calls.length === 0) {
      finalText = msg.content ?? "";
      break;
    }

    const toolResults = await Promise.all(
      msg.tool_calls.map(async (tc) => {
        const handler = toolRegistry[tc.function.name];
        if (!handler) {
          return {
            tool_call_id: tc.id,
            error: `Unknown tool: ${tc.function.name}`,
          };
        }
        toolsUsed.push(tc.function.name);
        try {
          const args = JSON.parse(tc.function.arguments);
          const result = await handler(args);
          return { tool_call_id: tc.id, result };
        } catch (err: any) {
          logger.error({ err, tool: tc.function.name }, "tool failed");
          return {
            tool_call_id: tc.id,
            error: err.message ?? String(err),
          };
        }
      })
    );

    for (const r of toolResults) {
      messages.push({
        role: "tool",
        tool_call_id: r.tool_call_id,
        content: JSON.stringify(r.error ? { error: r.error } : r.result),
      });
    }
  }

  if (!finalText) {
    finalText = "I hit the max tool-call limit without finishing. Try rephrasing.";
  }

  await persistTurn({
    channelId: input.channelId,
    slackUserId: input.slackUserId,
    userMessage: input.userMessage,
    finalText,
    messages,
    toolsUsed,
    iterations,
    latencyMs: Date.now() - startedAt,
    inputTokens,
    outputTokens,
  });

  return { text: finalText, toolsUsed, iterations };
}
```

### 6.3 Slack signature verification (`src/integrations/slack.ts`)

```ts
import crypto from "node:crypto";
import { WebClient } from "@slack/web-api";
import { config } from "../config";

export const slack = new WebClient(config.SLACK_BOT_TOKEN);

export function verifySlackSignature(
  rawBody: string,
  timestamp: string | undefined,
  signature: string | undefined
): { valid: boolean; reason?: string } {
  if (!timestamp || !signature) {
    return { valid: false, reason: "missing_headers" };
  }
  const fiveMinutes = 60 * 5;
  if (Math.abs(Math.floor(Date.now() / 1000) - parseInt(timestamp, 10)) > fiveMinutes) {
    return { valid: false, reason: "timestamp_expired" };
  }
  const sigBasestring = `v0:${timestamp}:${rawBody}`;
  const mySig = "v0=" + crypto
    .createHmac("sha256", config.SLACK_SIGNING_SECRET)
    .update(sigBasestring, "utf8")
    .digest("hex");
  try {
    const valid = crypto.timingSafeEqual(Buffer.from(mySig), Buffer.from(signature));
    return { valid, reason: valid ? "ok" : "signature_mismatch" };
  } catch {
    return { valid: false, reason: "length_mismatch" };
  }
}
```

### 6.35 Background work on Node + Slack `event_id` dedupe

`c.executionCtx.waitUntil()` only exists on runtimes like Cloudflare Workers. On **Node**, returning from the route ends the HTTP response, but the **event loop keeps running** as long as there are pending promises—so you start the async function and **do not await it**, and attach a `.catch` so rejections are never unhandled.

Slack may deliver the same `event_callback` more than once. Each delivery includes a stable top-level **`event_id`**. Acknowledge duplicates with `200 OK` and **skip** work so you do not double-react or double-call the model.

**`src/utils/dispatch.ts`**

```ts
import { logger } from "./logger";

/** Fire-and-forget on Node. Replaces Workers `executionCtx.waitUntil`. */
export function dispatchDetached(label: string, work: () => Promise<void>): void {
  void work().catch((err) => {
    logger.error({ err, label }, "background task failed");
  });
}
```

**`src/integrations/slack-dedupe.ts`** (fine for a single app process; use Postgres/Redis if you ever run multiple replicas)

```ts
const TTL_MS = 60 * 60 * 1000; // 1h; Slack retries are short-lived
const seen = new Map<string, number>(); // event_id -> lastSeenEpochMs

function prune(now: number) {
  for (const [id, t] of seen) {
    if (now - t > TTL_MS) seen.delete(id);
  }
}

/** @returns true if this event_id was already handled (duplicate delivery). */
export function isDuplicateSlackEvent(eventId: string): boolean {
  const now = Date.now();
  prune(now);
  if (seen.has(eventId)) return true;
  seen.set(eventId, now);
  return false;
}
```

For **horizontal scaling**, replace the `Map` with `INSERT INTO slack_events(event_id) ... ON CONFLICT DO NOTHING` returning whether a row was inserted.

**Dedupe trade-off:** Recording `event_id` before work starts prevents overlapping duplicate deliveries from running the agent twice. If the process dies after recording but before finishing, Slack’s retry may be treated as a duplicate and skipped. For stricter recovery, persist `event_id` only **after** a successful handler (and use a DB-level “claim” with a unique constraint if you run multiple app instances so two boxes cannot both process the same event).

### 6.4 Slack route (`src/routes/slack.ts`)

```ts
import { Hono } from "hono";
import { verifySlackSignature, slack } from "../integrations/slack";
import { isDuplicateSlackEvent } from "../integrations/slack-dedupe";
import { dispatchDetached } from "../utils/dispatch";
import { runAgent } from "../agent/loop";
import { logger } from "../utils/logger";

export const slackRoutes = new Hono();

slackRoutes.post("/events", async (c) => {
  const rawBody = await c.req.text();
  const timestamp = c.req.header("x-slack-request-timestamp");
  const signature = c.req.header("x-slack-signature");

  const { valid, reason } = verifySlackSignature(rawBody, timestamp, signature);
  if (!valid) {
    logger.warn({ reason }, "invalid slack signature");
    return c.text("Unauthorized", 401);
  }

  const body = JSON.parse(rawBody);

  if (body.type === "url_verification") {
    return c.json({ challenge: body.challenge });
  }

  if (body.type === "event_callback" && typeof body.event_id === "string") {
    if (isDuplicateSlackEvent(body.event_id)) {
      return c.text("OK");
    }
  }

  dispatchDetached("slack-event", () => handleEvent(body));
  return c.text("OK");
});

async function handleEvent(body: any) {
  const event = body.event;
  if (
    !event ||
    event.bot_id ||
    event.subtype === "bot_message" ||
    event.subtype === "message_changed" ||
    event.channel_type !== "im"
  ) {
    return;
  }

  const userMessage = typeof event.text === "string" ? event.text : "";
  if (!userMessage.trim()) {
    return;
  }

  try {
    await slack.reactions.add({
      channel: event.channel,
      timestamp: event.ts,
      name: "eyes",
    });

    const { text } = await runAgent({
      channelId: event.channel,
      slackUserId: event.user,
      userMessage,
    });

    await slack.chat.postMessage({
      channel: event.channel,
      text,
    });

    await slack.reactions.add({
      channel: event.channel,
      timestamp: event.ts,
      name: "white_check_mark",
    });
  } catch (err: any) {
    logger.error({ err }, "agent handler failed");
    await slack.chat.postMessage({
      channel: event.channel,
      text: `:warning: Something broke: ${err.message ?? "unknown"}`,
    }).catch(() => {});
  }
}
```

### 6.5 Tool registry pattern (`src/agent/registry.ts`)

```ts
import { notionTools } from "../tools/notion";
import { gmailTools } from "../tools/gmail";
import { calendarTools } from "../tools/calendar";
import { githubTools } from "../tools/github";
import { granolaTools } from "../tools/granola"; // optional

type ToolHandler = (args: any) => Promise<unknown>;
type ToolDef = { spec: any; handler: ToolHandler };

const allTools: Record<string, ToolDef> = {
  ...notionTools,
  ...gmailTools,
  ...calendarTools,
  ...githubTools,
  ...granolaTools,
};

export const toolRegistry: Record<string, ToolHandler> = Object.fromEntries(
  Object.entries(allTools).map(([k, v]) => [k, v.handler])
);

export const toolSpecs = Object.values(allTools).map((t) => t.spec);
```

### 6.6 One tool example (`src/tools/notion.ts`, just `notion_search_projects`)

```ts
import { Client } from "@notionhq/client";
import { config } from "../config";

const notion = new Client({ auth: config.NOTION_TOKEN });

export const notionTools = {
  notion_search_projects: {
    spec: {
      type: "function",
      function: {
        name: "notion_search_projects",
        description:
          "Search projects in the Projects Notion database. " +
          "Returns up to 20 projects with Name, Status, Deadline, page ID. " +
          "Optional status filter: Backlog, In Progress, Done, Blocked.",
        parameters: {
          type: "object",
          properties: {
            status: { type: "string", description: "Optional status filter" },
            limit: { type: "integer", description: "Max results, default 20" },
          },
        },
      },
    },
    handler: async (args: { status?: string; limit?: number }) => {
      const filter = args.status
        ? { property: "Status", status: { equals: args.status } }
        : undefined;
      const res = await notion.databases.query({
        database_id: config.NOTION_PROJECTS_DB_ID,
        filter,
        page_size: args.limit ?? 20,
      });
      return res.results.map((p: any) => ({
        id: p.id,
        name: p.properties.Name?.title?.[0]?.plain_text ?? "Untitled",
        status: p.properties.Status?.status?.name ?? "",
        deadline: p.properties.Deadline?.date?.start ?? null,
        url: p.url,
      }));
    },
  },
  // ...notion_create_project, notion_update_project, notion_search_tasks, etc.
};
```

This is the pattern for all 23 tools: spec (OpenAI function format) plus handler (typed function calling the underlying API).

### 6.7 Cron route (`src/routes/cron.ts`)

```ts
import { Hono } from "hono";
import { config } from "../config";
import { dispatchDetached } from "../utils/dispatch";
import { runDailyBrief } from "../jobs/daily-brief";

export const cronRoutes = new Hono();

cronRoutes.use("*", async (c, next) => {
  const auth = c.req.header("authorization");
  if (auth !== `Bearer ${config.CRON_SECRET}`) {
    return c.text("Unauthorized", 401);
  }
  await next();
});

cronRoutes.post("/daily-brief", async (c) => {
  dispatchDetached("daily-brief", () => runDailyBrief());
  return c.json({ ok: true, dispatched: true });
});
```

### 6.8 GitHub Actions cron (`.github/workflows/cron-daily-brief.yml`)

```yaml
name: Daily Brief
on:
  schedule:
    - cron: "0 7 * * 1-5"  # 7am UTC = 8am Europe/London
  workflow_dispatch:

jobs:
  trigger:
    runs-on: ubuntu-latest
    steps:
      - name: Hit daily-brief endpoint
        run: |
          curl -fsSL -X POST "${{ secrets.AGENT_BASE_URL }}/cron/daily-brief" \
            -H "Authorization: Bearer ${{ secrets.CRON_SECRET }}" \
            -H "Content-Type: application/json" \
            --max-time 30
```

Repo secrets needed: `AGENT_BASE_URL` (e.g. `https://cto-agent.yamlgroup.tech`) and `CRON_SECRET`.

---

## 7. Phased Build Plan

Each phase is independently testable. Don't move on until the previous phase passes.

### Phase 0: Bootstrap (1 hour)
```bash
cd /Users/sooreoluwa/Projects/_ai-agents/cto-agent
pnpm init
pnpm add hono @hono/node-server openai @slack/web-api \
  @notionhq/client googleapis octokit \
  drizzle-orm postgres zod pino dotenv
pnpm add -D typescript tsx @types/node drizzle-kit @types/pg
```
Set up `tsconfig.json`, `.env.example`, `src/index.ts` minimal Hono server, `/healthz` route.
Acceptance: `pnpm dev` runs, `curl localhost:3000/healthz` returns OK.

### Phase 1: Postgres + Drizzle (1 hour)
Use a hosted or local Postgres; set `DATABASE_URL`. Write `src/memory/schema.ts`. Configure `drizzle.config.ts`. Generate and run migrations.
Acceptance: `pnpm drizzle:push` succeeds, tables exist when you connect via psql.

### Phase 2: Slack webhook with signature verify (2 hours)
Build `src/routes/slack.ts`, `src/integrations/slack.ts`, `src/utils/dispatch.ts`, and `src/integrations/slack-dedupe.ts`. Add URL verification handler. Use `dispatchDetached` for async handling (not `waitUntil`). Echo back any received message text (no agent yet) just to prove the loop.
Acceptance: Slack DM `hello` round-trips through the server, posts `Echo: hello`.

### Phase 3: Agent loop with no tools (2 hours)
Build `src/agent/llm.ts`, `src/agent/prompt.ts`, `src/agent/loop.ts`. Empty tool registry. Persist messages to Postgres.
Acceptance: DM the bot, get a real conversational reply from Sonnet. Memory works (ask "what did I just say" and it recalls).

### Phase 4: Notion tools (2 hours)
Build `src/tools/notion.ts` with 6 tools. Wire into registry.
Acceptance: "List my projects" returns Notion data. "Create project X" prompts for confirmation, then creates on yes.

### Phase 5: Gmail tools (3 hours)
Set up Google OAuth refresh token (one-time, see section 8). Build `src/tools/gmail.ts` with 4 tools.
Acceptance: "Search unread emails from Tunde" returns matches. Drafts work, send requires explicit yes.

### Phase 6: Calendar tools (1 hour, reuses Google OAuth)
Build `src/tools/calendar.ts` with 5 tools.
Acceptance: "What's on my calendar tomorrow" works. Create/update/delete events with confirmation.

### Phase 7: GitHub tools (1 hour)
PAT auth via env. Build `src/tools/github.ts` with 5 tools.
Acceptance: "List open PRs in repo X" works. CI status surfaces failures first.

### Phase 8: Granola tools (1 hour, optional)
Skip if no Granola API access. Otherwise build `src/tools/granola.ts`.
Acceptance: "What did I commit to in yesterday's standup" works.

### Phase 9: Daily brief job + GitHub Actions (2 hours)
Build `src/jobs/daily-brief.ts` and `src/routes/cron.ts`. Add GitHub Actions workflow.
Acceptance: Manual `workflow_dispatch` runs and a brief lands in your DM. Cron schedule fires at 7am UTC tomorrow.

### Phase 10: Docker image + deploy (2 hours)
Finalize multi-stage `Dockerfile`. Deploy the image on your platform (e.g. **Coolify**: connect repo, set env from `.env.example`, expose `PORT`, run `pnpm drizzle:push` or migrate against production `DATABASE_URL`). Update Slack Event Subscriptions URL to your public `/slack/events`.
Acceptance: Slack DM works against the production endpoint, not localhost.

**Total: 17 to 18 hours of focused work. Spread over a week comfortably.**

---

## 8. Google OAuth Refresh Token Setup (One-Time, 20 min)

Generating the refresh token is the trickiest part. Do this once, store it as `GOOGLE_REFRESH_TOKEN` in env.

1. Google Cloud Console > new project > enable Gmail API and Google Calendar API
2. OAuth consent screen > External > add yourself as test user
3. Credentials > OAuth client ID > Web application
4. Authorized redirect URI: `https://developers.google.com/oauthplayground`
5. Save Client ID and Secret
6. Open https://developers.google.com/oauthplayground
7. Settings (gear icon, top right) > tick "Use your own OAuth credentials" > paste your Client ID and Secret
8. Step 1 left panel: paste these scopes manually:
   ```
   https://www.googleapis.com/auth/gmail.modify
   https://www.googleapis.com/auth/gmail.send
   https://www.googleapis.com/auth/calendar
   https://www.googleapis.com/auth/calendar.events
   ```
9. Authorize APIs > sign in with your Google account > Allow
10. Step 2: Exchange authorization code for tokens
11. Copy the **Refresh token** value. This is what you store in `GOOGLE_REFRESH_TOKEN`.

In code, you instantiate the OAuth2 client with client ID + secret + refresh token, and `googleapis` handles access token refresh automatically.

---

## 9. Deployment

### Dockerfile (multi-stage)

```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN corepack enable && pnpm build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
COPY --from=build /app/drizzle ./drizzle
EXPOSE 3000
CMD ["node", "dist/index.js"]
```

### Deploy (generic)

1. Build and run the **`Dockerfile`** (or let **Coolify** / CI build it). Ensure **`DATABASE_URL`** and all secrets are set in the platform env (see **§4**).
2. Apply migrations: `drizzle-kit push` or generated migrations, pointed at production Postgres.
3. Set Slack **Event Subscriptions** **Request URL** to `https://<your-public-host>/slack/events`.

This repo does **not** ship `docker-compose` or a `Caddyfile`; routing and TLS are handled by your deployment environment.

**Coolify:** connect the Git repo, use **Dockerfile** build, set port to **`PORT`** (default 3000), health check **`/healthz`**.

---

## 10. Acceptance Tests

Run these in order. Each one should pass before moving to the next phase. Final pass = ship.

### Smoke
1. `GET /healthz` returns 200
2. DM `hello`. Get conversational reply within 5 seconds.

### Phase 4: Notion
1. `What projects are in progress?` returns filtered list
2. `Create a project called Acceptance Test, status Backlog, deadline 2026-05-15` then `yes`
3. `What did I just create?` recalls from memory (no Notion call needed)
4. `Update Acceptance Test deadline to 2026-05-22` then `yes`
5. `Create a task called Write tests under Acceptance Test, due tomorrow` then `yes`

### Phase 5: Gmail
1. `What unread emails do I have this week?`
2. `Read the latest one in detail`
3. `Draft a reply saying I'll review tomorrow` (returns draft URL, no send)
4. `Send it` (only after explicit yes)

### Phase 6: Calendar
1. `What's on my calendar tomorrow?`
2. `Create a 30-min meeting called Sync at 3pm tomorrow` then `yes`
3. `Move it to 4pm` then `yes`
4. `Delete it` then `yes` then `yes` (double confirmation)

### Phase 7: GitHub
1. `List my open PRs in cto-agent`
2. `What's the CI status on main?` (failures surface first)
3. `Show me the README of cto-agent`

### Phase 9: Daily Brief
1. Trigger workflow manually via `gh workflow run cron-daily-brief.yml`
2. Brief lands in DM with sections for Today, Inbox, Code, Projects

### Cross-tool reasoning (the real test)
1. `What did I commit to in yesterday's standup, and is any of it tracked in Notion?` (Granola + Notion)
2. `Move the Acceptance Test deadline to next Friday and email me a confirmation` (Notion + Gmail with confirmation)
3. `What's broken on main and what tasks are blocking the fix?` (GitHub + Notion)

### Hardening
1. Bad signature: send a fake POST without proper signature. Get 401.
2. Replay attack: send valid request with timestamp older than 5 min. Get 401.
3. Duplicate Slack delivery: POST the same `event_callback` body twice (same `event_id`). First run processes; second returns 200 with no second DM or duplicate reactions.
4. Tool failure: revoke Notion token temporarily. Agent reports error cleanly.
5. Long conversation: 50 messages back and forth. Memory window slides correctly.

---

## 11. Cost Model

Per turn cost (Sonnet 4.6 via OpenRouter, current pricing):
- Input: ~$3 per million tokens
- Output: ~$15 per million tokens

Typical conversation turn:
- System prompt: ~1500 tokens
- 12 turns of history: ~3000 tokens
- User message: ~50 tokens
- Tool results (1 to 3 calls): ~1000 tokens
- Output: ~300 tokens
- Total: ~6000 in + 300 out = ~$0.022 per turn

At 30 turns/day = $0.66/day = ~$20/month. Matches the budget you set.

Daily brief: single LLM call, ~$0.05 per day = $1/month.

Buffer: keep $25/month allocated. Set OpenRouter usage alert at $20.

---

## 12. Operational Notes

### Observability
- pino logger writes structured JSON to stdout
- Postgres `logs` table is your queryable history (latency, tools, success rate)
- Add Grafana later if you want dashboards

### Backups
- Daily `pg_dump` cron on the VPS, sync to S3 or Backblaze
- Without backups you lose conversation memory if Postgres dies

### Rotation
- Slack tokens: rotate every 6 months
- GitHub PAT: 90-day expiration, GitHub emails you before expiry
- Google refresh token: long-lived but invalidates if you change Google password
- OpenRouter key: no expiry, rotate yearly out of habit

### Cost guard
Add a daily check: if today's spend in `logs` table exceeds threshold, return a "budget exceeded" message instead of calling the LLM. One SQL query, 10 lines of code.

---

## 13. Why This Architecture Beats n8n for This Use Case

| Concern | n8n | This codebase |
|---|---|---|
| Adding a tool | Click 8 fields in UI | One typed function |
| Changing system prompt | Edit JSON inside node | Edit `prompt.ts` |
| Code review | Diff is unreadable | Clean PRs |
| Unit test a tool | Not really possible | `vitest` against the handler |
| Memory | Buffer in process, lost on restart | Postgres, durable |
| Custom retry/parallel | Limited | Whatever you want |
| Latency | n8n execution overhead | Direct API calls |
| Lock-in | Medium | None, OpenAI spec |

The trade-off you accept: more upfront setup. The win: 6 months from now, the agent is still maintainable.

---

## 14. Files To Read Next

- `cto-agent-process-plan.md` (in workspace folder) for the high-level roadmap
- `IMPLEMENTATION.md` (this file) for the actual build
- `cto-agent-full-setup.md` (in workspace folder) for the credential checklist (still applies, just ignore the n8n-specific parts)

When you're ready, start at Phase 0 above. Create files as you go. Commit after each phase. Don't skip the acceptance tests.
