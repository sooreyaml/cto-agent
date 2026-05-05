import type { ChatCompletionMessageParam } from "openai/resources/chat/completions";
import { llm, MODEL } from "./llm.js";
import { buildSystemPrompt } from "./prompt.js";
import { toolRegistry, toolSpecs } from "./registry.js";
import { loadHistory, persistTurn } from "../memory/repository.js";
import { logger } from "../utils/logger.js";

export type AgentInput = {
  channelId: string;
  slackUserId: string;
  /** Plain text from Slack (may be empty if only images). */
  userMessage: string;
  /** Data URLs `data:image/...;base64,...` from Slack file downloads. */
  imageDataUrls?: string[];
};

const MAX_ITERATIONS = 10;

export async function runAgent(input: AgentInput) {
  const startedAt = Date.now();
  const toolsUsed: string[] = [];
  let inputTokens = 0;
  let outputTokens = 0;

  const history = await loadHistory(input.channelId, 24);
  const historyLen = history.length;

  const textPart = input.userMessage.trim() || "(User sent an image with no caption.)";
  const userMsg: ChatCompletionMessageParam =
    input.imageDataUrls && input.imageDataUrls.length > 0
      ? {
          role: "user",
          content: [
            { type: "text", text: textPart },
            ...input.imageDataUrls.map(
              (url) =>
                ({
                  type: "image_url",
                  image_url: { url },
                }) as const
            ),
          ],
        }
      : { role: "user", content: input.userMessage };

  const messages: ChatCompletionMessageParam[] = [
    { role: "system", content: buildSystemPrompt() },
    ...history,
    userMsg,
  ];

  let finalText = "";
  let iterations = 0;

  for (let i = 0; i < MAX_ITERATIONS; i++) {
    iterations++;
    const response = await llm.chat.completions.create({
      model: MODEL,
      messages,
      ...(toolSpecs.length > 0
        ? { tools: toolSpecs, tool_choice: "auto" as const }
        : {}),
      temperature: 0.3,
      max_tokens: 2048,
    });

    inputTokens += response.usage?.prompt_tokens ?? 0;
    outputTokens += response.usage?.completion_tokens ?? 0;

    const msg = response.choices[0]?.message;
    if (!msg) break;

    messages.push(msg as ChatCompletionMessageParam);

    if (!msg.tool_calls?.length) {
      finalText = msg.content ?? "";
      break;
    }

    const toolResults = await Promise.all(
      msg.tool_calls.map(async (tc) => {
        if (tc.type !== "function") {
          return {
            tool_call_id: tc.id,
            error: `Unsupported tool call type: ${tc.type}`,
          };
        }
        const handler = toolRegistry[tc.function.name];
        if (!handler) {
          return {
            tool_call_id: tc.id,
            error: `Unknown tool: ${tc.function.name}`,
          };
        }
        toolsUsed.push(tc.function.name);
        try {
          const args = JSON.parse(tc.function.arguments ?? "{}") as unknown;
          const result = await handler(args);
          return { tool_call_id: tc.id, result };
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : String(err);
          logger.error({ err, tool: tc.function.name }, "tool failed");
          return {
            tool_call_id: tc.id,
            error: message,
          };
        }
      })
    );

    for (const r of toolResults) {
      const content =
        "error" in r
          ? JSON.stringify({ error: r.error })
          : JSON.stringify((r as { result: unknown }).result);
      messages.push({
        role: "tool",
        tool_call_id: r.tool_call_id,
        content,
      });
    }
  }

  if (!finalText) {
    finalText =
      "I hit the max tool-call limit without finishing. Try rephrasing.";
  }

  const logUserSummary =
    input.imageDataUrls?.length ?
      `${input.userMessage.trim() || "[no text]"} [${input.imageDataUrls.length} image(s)]`
    : input.userMessage;

  try {
    await persistTurn({
      channelId: input.channelId,
      slackUserId: input.slackUserId,
      userMessage: logUserSummary,
      finalText,
      messages,
      historyLen,
      toolsUsed,
      iterations,
      latencyMs: Date.now() - startedAt,
      inputTokens,
      outputTokens,
    });
  } catch (err) {
    logger.error({ err }, "persistTurn failed");
  }

  return { text: finalText, toolsUsed, iterations };
}
