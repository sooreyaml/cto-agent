import { Hono } from "hono";
import { verifySlackSignature, slack } from "../integrations/slack.js";
import { isDuplicateSlackEvent } from "../integrations/slack-dedupe.js";
import { dispatchDetached } from "../utils/dispatch.js";
import { runAgent } from "../agent/loop.js";
import { logger } from "../utils/logger.js";

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

  let body: { type?: string; challenge?: string; event_id?: string; event?: SlackEvent };
  try {
    body = JSON.parse(rawBody) as typeof body;
  } catch {
    return c.text("Bad Request", 400);
  }

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

type SlackEvent = {
  type?: string;
  channel?: string;
  user?: string;
  text?: string;
  ts?: string;
  bot_id?: string;
  subtype?: string;
  channel_type?: string;
};

async function handleEvent(body: { event?: SlackEvent }) {
  const event = body.event;
  if (
    !event ||
    event.type !== "message" ||
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
      channel: event.channel!,
      timestamp: event.ts!,
      name: "eyes",
    });

    const { text } = await runAgent({
      channelId: event.channel!,
      slackUserId: event.user!,
      userMessage,
    });

    await slack.chat.postMessage({
      channel: event.channel!,
      text,
    });

    await slack.reactions.add({
      channel: event.channel!,
      timestamp: event.ts!,
      name: "white_check_mark",
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "unknown";
    logger.error({ err }, "agent handler failed");
    if (event.channel) {
      await slack.chat
        .postMessage({
          channel: event.channel,
          text: `:warning: Something broke: ${message}`,
        })
        .catch(() => {});
    }
  }
}
