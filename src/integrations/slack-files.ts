import { config } from "../config.js";
import { logger } from "../utils/logger.js";

/** Minimal Slack `files[]` shape on `message` events. */
export type SlackFile = {
  mimetype?: string;
  url_private?: string;
  url_private_download?: string;
};

const IMAGE_MIME = /^image\/(png|jpeg|jpg|gif|webp)$/i;

/**
 * Download Slack-hosted images using the bot token (requires `files:read` scope).
 * Returns data URLs suitable for OpenAI-compatible `image_url` fields.
 */
export async function fetchSlackImageDataUrls(
  files: SlackFile[] | undefined,
  options: { maxImages?: number; maxBytesPerFile?: number } = {}
): Promise<string[]> {
  const maxImages = options.maxImages ?? 4;
  const maxBytes = options.maxBytesPerFile ?? 5 * 1024 * 1024;

  if (!files?.length) return [];

  const out: string[] = [];
  for (const f of files) {
    if (out.length >= maxImages) break;
    if (!f.mimetype || !IMAGE_MIME.test(f.mimetype)) continue;

    const url = f.url_private_download ?? f.url_private;
    if (!url) continue;

    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${config.SLACK_BOT_TOKEN}` },
      });
      if (!res.ok) {
        logger.warn({ status: res.status }, "slack image download failed");
        continue;
      }
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length > maxBytes) {
        logger.warn({ bytes: buf.length }, "slack image too large; skipping");
        continue;
      }
      out.push(`data:${f.mimetype};base64,${buf.toString("base64")}`);
    } catch (err) {
      logger.warn({ err }, "slack image fetch error");
    }
  }
  return out;
}
