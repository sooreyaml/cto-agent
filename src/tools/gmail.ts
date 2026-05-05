import type { ToolDef } from "../agent/tool-types.js";
import { getGmail } from "../integrations/google.js";

const userId = "me";

function buildRawMime(to: string, subject: string, body: string): string {
  const lines = [
    to.includes("<") ? `To: ${to}` : `To: <${to}>`,
    `Subject: ${subject}`,
    "Content-Type: text/plain; charset=utf-8",
    "",
    body,
  ];
  return lines.join("\r\n");
}

function encodeRaw(raw: string): string {
  return Buffer.from(raw, "utf8").toString("base64url");
}

export const gmailTools: Record<string, ToolDef> = {
  gmail_search_messages: {
    spec: {
      type: "function",
      function: {
        name: "gmail_search_messages",
        description:
          "Search Gmail with Gmail query syntax (e.g. is:unread, from:x, newer_than:7d). Returns id, snippet, subject preview.",
        parameters: {
          type: "object",
          properties: {
            query: { type: "string", description: "Gmail search query" },
            max_results: { type: "integer", description: "1–20, default 10" },
          },
          required: ["query"],
        },
      },
    },
    handler: async (args: { query: string; max_results?: number }) => {
      const gmail = getGmail();
      const max = Math.min(Math.max(args.max_results ?? 10, 1), 20);
      const list = await gmail.users.messages.list({
        userId,
        q: args.query,
        maxResults: max,
      });
      const ids = list.data.messages?.map((m) => m.id).filter(Boolean) as string[];
      if (!ids?.length) return [];
      const out: { id: string; threadId?: string; snippet?: string; subject?: string }[] = [];
      for (const id of ids) {
        const msg = await gmail.users.messages.get({
          userId,
          id,
          format: "metadata",
          metadataHeaders: ["Subject"],
        });
        const headers = msg.data.payload?.headers;
        const subj = headers?.find((h) => h.name?.toLowerCase() === "subject")?.value;
        out.push({
          id,
          threadId: msg.data.threadId ?? undefined,
          snippet: msg.data.snippet ?? undefined,
          subject: subj ?? undefined,
        });
      }
      return out;
    },
  },

  gmail_get_message: {
    spec: {
      type: "function",
      function: {
        name: "gmail_get_message",
        description: "Fetch a single Gmail message by id (snippet + plain text body if available).",
        parameters: {
          type: "object",
          properties: {
            message_id: { type: "string" },
            format: {
              type: "string",
              enum: ["full", "metadata"],
              description: "Default full",
            },
          },
          required: ["message_id"],
        },
      },
    },
    handler: async (args: { message_id: string; format?: "full" | "metadata" }) => {
      const gmail = getGmail();
      const msg = await gmail.users.messages.get({
        userId,
        id: args.message_id,
        format: args.format ?? "full",
      });
      const headers = msg.data.payload?.headers ?? [];
      const subject = headers.find((h) => h.name?.toLowerCase() === "subject")?.value;
      const from = headers.find((h) => h.name?.toLowerCase() === "from")?.value;
      let body = "";
      const extract = (part: typeof msg.data.payload): void => {
        if (!part) return;
        if (part.mimeType === "text/plain" && part.body?.data) {
          body += Buffer.from(part.body.data, "base64").toString("utf8");
        }
        if (part.parts) part.parts.forEach(extract);
      };
      extract(msg.data.payload);
      return {
        id: msg.data.id,
        threadId: msg.data.threadId,
        snippet: msg.data.snippet,
        subject,
        from,
        body: body || msg.data.snippet,
      };
    },
  },

  gmail_create_draft: {
    spec: {
      type: "function",
      function: {
        name: "gmail_create_draft",
        description: "Create a draft email. Does not send.",
        parameters: {
          type: "object",
          properties: {
            to: { type: "string", description: "Recipient email" },
            subject: { type: "string" },
            body: { type: "string", description: "Plain text body" },
          },
          required: ["to", "subject", "body"],
        },
      },
    },
    handler: async (args: { to: string; subject: string; body: string }) => {
      const gmail = getGmail();
      const raw = encodeRaw(buildRawMime(args.to, args.subject, args.body));
      const draft = await gmail.users.drafts.create({
        userId,
        requestBody: { message: { raw } },
      });
      return {
        draftId: draft.data.id,
        messageId: draft.data.message?.id,
        threadId: draft.data.message?.threadId,
      };
    },
  },

  gmail_send_message: {
    spec: {
      type: "function",
      function: {
        name: "gmail_send_message",
        description:
          "Send an email immediately (plain text). Use only after user explicitly confirms. Uses configured Google account.",
        parameters: {
          type: "object",
          properties: {
            to: { type: "string" },
            subject: { type: "string" },
            body: { type: "string" },
          },
          required: ["to", "subject", "body"],
        },
      },
    },
    handler: async (args: { to: string; subject: string; body: string }) => {
      const gmail = getGmail();
      const raw = encodeRaw(buildRawMime(args.to, args.subject, args.body));
      const sent = await gmail.users.messages.send({
        userId,
        requestBody: { raw },
      });
      return { id: sent.data.id, threadId: sent.data.threadId, labelIds: sent.data.labelIds };
    },
  },
};
