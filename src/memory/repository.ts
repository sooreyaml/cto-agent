import { eq, desc, max } from "drizzle-orm";
import type { ChatCompletionMessageParam } from "openai/resources/chat/completions";
import { db } from "./db.js";
import { conversations, messages, logs } from "./schema.js";

function rowToParam(row: typeof messages.$inferSelect): ChatCompletionMessageParam {
  if (row.role === "tool") {
    return {
      role: "tool",
      tool_call_id: row.toolCallId ?? "",
      content: row.content ?? "",
    };
  }
  if (row.role === "assistant") {
    if (row.toolCalls) {
      return {
        role: "assistant",
        content: row.content,
        tool_calls: row.toolCalls as NonNullable<
          Extract<ChatCompletionMessageParam, { role: "assistant" }>["tool_calls"]
        >,
      };
    }
    return { role: "assistant", content: row.content };
  }
  return { role: "user", content: row.content ?? "" };
}

function messageToInsert(
  conversationId: string,
  msg: ChatCompletionMessageParam,
  sortSeq: number,
): typeof messages.$inferInsert {
  if (msg.role === "tool") {
    return {
      conversationId,
      role: "tool",
      content: typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content),
      toolCallId: msg.tool_call_id,
      sortSeq,
    };
  }
  if (msg.role === "assistant") {
    const c = msg.content;
    let text: string | null = null;
    if (typeof c === "string") text = c;
    else if (Array.isArray(c)) {
      text = c.map((p) => ("text" in p ? p.text : JSON.stringify(p))).join("");
    }
    return {
      conversationId,
      role: "assistant",
      content: text,
      toolCalls: msg.tool_calls ?? null,
      sortSeq,
    };
  }
  if (msg.role === "user") {
    let content: string;
    if (typeof msg.content === "string") {
      content = msg.content;
    } else if (Array.isArray(msg.content)) {
      const parts = msg.content.map((p) => {
        if (p.type === "text") return p.text;
        if (p.type === "image_url") return "[image]";
        return "";
      });
      content = parts.filter(Boolean).join(" ").trim() || "[image]";
    } else {
      content = "";
    }
    return { conversationId, role: "user", content, sortSeq };
  }
  throw new Error(`Cannot persist message role: ${(msg as ChatCompletionMessageParam).role}`);
}

/** Drop tool messages with no matching assistant tool_calls, and trim incomplete tool rounds. */
export function sanitizeToolHistory(
  msgs: ChatCompletionMessageParam[],
): ChatCompletionMessageParam[] {
  const out: ChatCompletionMessageParam[] = [];
  let expectedToolIds: Set<string> | undefined;

  for (const m of msgs) {
    if (m.role === "user") {
      expectedToolIds = undefined;
      out.push(m);
      continue;
    }
    if (m.role === "assistant") {
      out.push(m);
      const tc =
        "tool_calls" in m && m.tool_calls?.length ?
          m.tool_calls
        : undefined;
      if (tc) {
        expectedToolIds = new Set(
          tc.filter((t) => t.type === "function").map((t) => t.id),
        );
      } else {
        expectedToolIds = undefined;
      }
      continue;
    }
    if (m.role === "tool") {
      const id = m.tool_call_id ?? "";
      if (id && expectedToolIds?.has(id)) {
        out.push(m);
        expectedToolIds.delete(id);
        if (expectedToolIds.size === 0) expectedToolIds = undefined;
      }
      continue;
    }
  }

  while (out.length > 0) {
    const last = out[out.length - 1]!;
    if (
      last.role === "assistant" &&
      "tool_calls" in last &&
      last.tool_calls &&
      last.tool_calls.length > 0
    ) {
      out.pop();
      continue;
    }
    break;
  }

  return out;
}

async function ensureConversation(channelId: string, slackUserId: string) {
  const [existing] = await db
    .select()
    .from(conversations)
    .where(eq(conversations.channelId, channelId))
    .limit(1);
  if (existing) {
    await db
      .update(conversations)
      .set({ lastActiveAt: new Date(), slackUserId })
      .where(eq(conversations.id, existing.id));
    return existing;
  }
  const [created] = await db
    .insert(conversations)
    .values({ channelId, slackUserId })
    .returning();
  if (!created) throw new Error("failed to create conversation");
  return created;
}

export async function loadHistory(
  channelId: string,
  limit: number
): Promise<ChatCompletionMessageParam[]> {
  const [conv] = await db
    .select()
    .from(conversations)
    .where(eq(conversations.channelId, channelId))
    .limit(1);
  if (!conv) return [];

  const rows = await db
    .select()
    .from(messages)
    .where(eq(messages.conversationId, conv.id))
    .orderBy(desc(messages.sortSeq), desc(messages.createdAt), desc(messages.id))
    .limit(limit);

  const raw = rows.reverse().map(rowToParam);
  return sanitizeToolHistory(raw);
}

export type PersistTurnInput = {
  channelId: string;
  slackUserId: string;
  userMessage: string;
  finalText: string;
  messages: ChatCompletionMessageParam[];
  historyLen: number;
  toolsUsed: string[];
  iterations: number;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  success?: boolean;
  errorMessage?: string | null;
};

export async function persistTurn(input: PersistTurnInput): Promise<void> {
  const conv = await ensureConversation(input.channelId, input.slackUserId);
  const tail = input.messages.slice(1 + input.historyLen);

  const [mx] = await db
    .select({ v: max(messages.sortSeq) })
    .from(messages)
    .where(eq(messages.conversationId, conv.id));
  let seq = (mx?.v ?? -1) + 1;

  for (const msg of tail) {
    if (msg.role === "system") continue;
    await db.insert(messages).values(messageToInsert(conv.id, msg, seq));
    seq += 1;
  }

  await db.insert(logs).values({
    channelId: input.channelId,
    slackUserId: input.slackUserId,
    userMessage: input.userMessage,
    agentOutput: input.finalText,
    toolsCalled: input.toolsUsed,
    iterations: input.iterations,
    latencyMs: input.latencyMs,
    inputTokens: input.inputTokens,
    outputTokens: input.outputTokens,
    success: input.success ?? true,
    errorMessage: input.errorMessage ?? null,
  });
}
