import { slack } from "../integrations/slack.js";
import { config } from "../config.js";
import type { ToolDef } from "../agent/tool-types.js";

/** DM channel opened with the bot for this Slack user. */
async function dmChannelIdForUser(slackUserId: string): Promise<string> {
  const opened = await slack.conversations.open({ users: slackUserId });
  const channel = opened.channel?.id;
  if (!channel) throw new Error("Could not open Slack DM for reminder");
  return channel;
}

function resolvePostAtSeconds(args: {
  post_at_unix?: number;
  in_minutes?: number;
  when_iso?: string;
}): number {
  const now = Math.floor(Date.now() / 1000);
  if (args.in_minutes != null && Number.isFinite(args.in_minutes)) {
    return now + Math.max(1, Math.floor(args.in_minutes)) * 60;
  }
  if (args.post_at_unix != null && Number.isFinite(args.post_at_unix)) {
    return Math.floor(args.post_at_unix);
  }
  if (args.when_iso?.trim()) {
    const ms = Date.parse(args.when_iso.trim());
    if (Number.isNaN(ms)) throw new Error("Invalid when_iso (use ISO 8601, e.g. 2026-05-10T15:00:00+01:00)");
    return Math.floor(ms / 1000);
  }
  throw new Error("Provide one of: in_minutes, post_at_unix, or when_iso");
}

function assertSlackScheduleWindow(postAt: number) {
  const now = Math.floor(Date.now() / 1000);
  const minAhead = 60;
  const maxAhead = 120 * 24 * 60 * 60;
  if (postAt < now + minAhead) {
    throw new Error(`Reminder must be at least ${minAhead} seconds from now (Slack limit)`);
  }
  if (postAt > now + maxAhead) {
    throw new Error("Reminder too far ahead (Slack allows up to about 120 days)");
  }
}

export const slackReminderTools: Record<string, ToolDef> = {
  slack_remind_at: {
    spec: {
      type: "function",
      function: {
        name: "slack_remind_at",
        description:
          "Schedule a Slack DM to the user at a future time (scheduled message — needs chat:write). Same UX as a reminder. Use NOTION/CTO Agent owner’s Slack user unless slack_user_id is set. Provide exactly one of in_minutes, post_at_unix, or when_iso.",
        parameters: {
          type: "object",
          properties: {
            text: { type: "string", description: "Reminder body (plain text)" },
            in_minutes: {
              type: "integer",
              description: "Send this many minutes from now",
            },
            post_at_unix: {
              type: "integer",
              description: "Unix time in seconds when to send",
            },
            when_iso: {
              type: "string",
              description: "ISO 8601 datetime (include offset or Z), e.g. 2026-07-27T18:00:00+01:00",
            },
            slack_user_id: {
              type: "string",
              description: "Optional Slack member ID (U…). Defaults to configured owner.",
            },
          },
          required: ["text"],
        },
      },
    },
    handler: async (args: {
      text: string;
      in_minutes?: number;
      post_at_unix?: number;
      when_iso?: string;
      slack_user_id?: string;
    }) => {
      const uid = (args.slack_user_id?.trim() || config.SLACK_USER_ID).trim();
      const explicit =
        [args.in_minutes, args.post_at_unix, args.when_iso?.trim()].filter(
          (x) => x !== undefined && x !== "",
        ).length;
      if (explicit !== 1) {
        throw new Error("Provide exactly one of: in_minutes, post_at_unix, or when_iso");
      }
      const postAt = resolvePostAtSeconds(args);
      assertSlackScheduleWindow(postAt);
      const channel = await dmChannelIdForUser(uid);
      const res = await slack.chat.scheduleMessage({
        channel,
        text: args.text,
        post_at: postAt,
      });
      if (!res.ok) {
        throw new Error((res as { error?: string }).error ?? "scheduleMessage failed");
      }
      return {
        ok: true,
        scheduled_message_id: res.scheduled_message_id,
        channel,
        post_at: postAt,
        post_at_iso: new Date(postAt * 1000).toISOString(),
      };
    },
  },

  slack_list_reminders: {
    spec: {
      type: "function",
      function: {
        name: "slack_list_reminders",
        description:
          "List scheduled DM reminders for the bot→user DM (scheduled messages). Optional slack_user_id for which user’s DM to inspect.",
        parameters: {
          type: "object",
          properties: {
            slack_user_id: {
              type: "string",
              description: "Optional Slack member ID; defaults to configured owner",
            },
            limit: { type: "integer", description: "Max items (default 20)" },
          },
        },
      },
    },
    handler: async (args: { slack_user_id?: string; limit?: number }) => {
      const uid = (args.slack_user_id?.trim() || config.SLACK_USER_ID).trim();
      const channel = await dmChannelIdForUser(uid);
      const res = await slack.chat.scheduledMessages.list({
        channel,
        limit: Math.min(args.limit ?? 20, 100),
      });
      if (!res.ok) {
        throw new Error((res as { error?: string }).error ?? "scheduledMessages.list failed");
      }
      const list = res.scheduled_messages ?? [];
      return {
        reminders: list.map((m) => ({
          scheduled_message_id: m.id,
          channel_id: m.channel_id,
          post_at: m.post_at,
          post_at_iso:
            m.post_at != null ? new Date(m.post_at * 1000).toISOString() : null,
          date_created: m.date_created,
          text: m.text,
        })),
      };
    },
  },

  slack_cancel_reminder: {
    spec: {
      type: "function",
      function: {
        name: "slack_cancel_reminder",
        description:
          "Cancel a scheduled DM reminder. Use scheduled_message_id from slack_list_reminders; channel_id must match that row (or pass slack_user_id to resolve the same DM).",
        parameters: {
          type: "object",
          properties: {
            scheduled_message_id: { type: "string" },
            channel_id: {
              type: "string",
              description: "DM channel ID from list; omit if slack_user_id is set (uses owner DM)",
            },
            slack_user_id: {
              type: "string",
              description: "If channel_id omitted, open this user’s DM with the bot",
            },
          },
          required: ["scheduled_message_id"],
        },
      },
    },
    handler: async (args: {
      scheduled_message_id: string;
      channel_id?: string;
      slack_user_id?: string;
    }) => {
      const channel =
        args.channel_id?.trim() ||
        (await dmChannelIdForUser(
          (args.slack_user_id?.trim() || config.SLACK_USER_ID).trim(),
        ));
      const res = await slack.chat.deleteScheduledMessage({
        channel,
        scheduled_message_id: args.scheduled_message_id,
      });
      if (!res.ok) {
        throw new Error((res as { error?: string }).error ?? "deleteScheduledMessage failed");
      }
      return { ok: true };
    },
  },
};
