import { eq, desc } from "drizzle-orm";
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
  msg: ChatCompletionMessageParam
): typeof messages.$inferInsert {
  if (msg.role === "tool") {
    return {
      conversationId,
      role: "tool",
      content: typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content),
      toolCallId: msg.tool_call_id,
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
    };
  }
  if (msg.role === "user") {
    const content =
      typeof msg.content === "string"
        ? msg.content
        : Array.isArray(msg.content)
          ? msg.content.map((p) => ("text" in p ? p.text : "")).join("\n")
          : "";
    return { conversationId, role: "user", content };
  }
  throw new Error(`Cannot persist message role: ${(msg as ChatCompletionMessageParam).role}`);
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
    .orderBy(desc(messages.createdAt))
    .limit(limit);

  return rows.reverse().map(rowToParam);
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

  for (const msg of tail) {
    if (msg.role === "system") continue;
    await db.insert(messages).values(messageToInsert(conv.id, msg));
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
