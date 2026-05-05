import crypto from "node:crypto";
import { WebClient } from "@slack/web-api";
import { config } from "../config.js";

export const slack = new WebClient(config.SLACK_BOT_TOKEN);

export type PostSlackMessageOptions = {
  /** Use Slack mrkdwn via Block Kit. Default false (plain `text` only). */
  mrkdwn?: boolean;
  /** Reply in the same thread as the user's message (recommended for DM threads). */
  thread_ts?: string;
};

function splitMrkdwnSections(body: string, maxLen = 2800): string[] {
  const t = body.trim();
  if (t.length <= maxLen) return [t];
  const parts: string[] = [];
  let rest = t;
  while (rest.length) {
    if (rest.length <= maxLen) {
      parts.push(rest);
      break;
    }
    let cut = rest.lastIndexOf("\n\n", maxLen);
    if (cut < maxLen * 0.4) cut = rest.lastIndexOf("\n", maxLen);
    if (cut < maxLen * 0.3) cut = maxLen;
    parts.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).trimStart();
  }
  return parts;
}

/** Post to any channel / DM id. Prefer `mrkdwn: true` for LLM copy so *bold* and `code` render. */
export async function postChannelMessage(
  channel: string,
  text: string,
  options: PostSlackMessageOptions = {}
): Promise<void> {
  const { mrkdwn = false, thread_ts } = options;

  if (mrkdwn) {
    const chunks = splitMrkdwnSections(text);
    const blocks = chunks.map((chunk) => ({
      type: "section" as const,
      text: { type: "mrkdwn" as const, text: chunk },
    }));
    const fallback = chunks.join("\n\n").replace(/[*_`<>]/g, "").slice(0, 400);
    await slack.chat.postMessage({
      channel,
      thread_ts,
      text: fallback || "CTO Agent",
      blocks,
    });
    return;
  }

  await slack.chat.postMessage({ channel, text, thread_ts });
}

/** Opens a DM and posts; same options as `postChannelMessage`. */
export async function postDmToUser(
  userId: string,
  text: string,
  options: PostSlackMessageOptions = {}
): Promise<void> {
  const opened = await slack.conversations.open({ users: userId });
  const channel = opened.channel?.id;
  if (!channel) throw new Error("Could not open Slack DM channel");
  await postChannelMessage(channel, text, options);
}

export function verifySlackSignature(
  rawBody: string,
  timestamp: string | undefined,
  signature: string | undefined
): { valid: boolean; reason?: string } {
  if (!timestamp || !signature) {
    return { valid: false, reason: "missing_headers" };
  }
  const fiveMinutes = 60 * 5;
  const ts = parseInt(timestamp, 10);
  if (Number.isNaN(ts)) {
    return { valid: false, reason: "bad_timestamp" };
  }
  if (Math.abs(Math.floor(Date.now() / 1000) - ts) > fiveMinutes) {
    return { valid: false, reason: "timestamp_expired" };
  }
  const sigBasestring = `v0:${timestamp}:${rawBody}`;
  const mySig =
    "v0=" +
    crypto.createHmac("sha256", config.SLACK_SIGNING_SECRET).update(sigBasestring, "utf8").digest("hex");
  try {
    const valid = crypto.timingSafeEqual(Buffer.from(mySig), Buffer.from(signature));
    return { valid, reason: valid ? "ok" : "signature_mismatch" };
  } catch {
    return { valid: false, reason: "length_mismatch" };
  }
}
