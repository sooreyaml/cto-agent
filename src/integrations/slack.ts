import crypto from "node:crypto";
import { WebClient } from "@slack/web-api";
import { config } from "../config.js";

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
