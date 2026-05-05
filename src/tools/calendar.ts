import { getCalendar } from "../integrations/google.js";
import { config } from "../config.js";
import type { ToolDef } from "../agent/tool-types.js";

const primaryCalendarId = "primary";

function tz() {
  return config.TIMEZONE || "UTC";
}

export const calendarTools: Record<string, ToolDef> = {
  calendar_list_events: {
    spec: {
      type: "function",
      function: {
        name: "calendar_list_events",
        description: "List Google Calendar events in a time window (ISO timeMin/timeMax).",
        parameters: {
          type: "object",
          properties: {
            time_min: { type: "string", description: "ISO 8601 start" },
            time_max: { type: "string", description: "ISO 8601 end" },
            max_results: { type: "integer" },
          },
          required: ["time_min", "time_max"],
        },
      },
    },
    handler: async (args: { time_min: string; time_max: string; max_results?: number }) => {
      const cal = getCalendar();
      const res = await cal.events.list({
        calendarId: primaryCalendarId,
        timeMin: args.time_min,
        timeMax: args.time_max,
        timeZone: tz(),
        singleEvents: true,
        orderBy: "startTime",
        maxResults: Math.min(args.max_results ?? 50, 250),
      });
      const items = res.data.items ?? [];
      return items.map((e) => ({
        id: e.id,
        summary: e.summary,
        start: e.start?.dateTime ?? e.start?.date,
        end: e.end?.dateTime ?? e.end?.date,
        htmlLink: e.htmlLink,
        status: e.status,
      }));
    },
  },

  calendar_get_event: {
    spec: {
      type: "function",
      function: {
        name: "calendar_get_event",
        description: "Get one calendar event by id.",
        parameters: {
          type: "object",
          properties: { event_id: { type: "string" } },
          required: ["event_id"],
        },
      },
    },
    handler: async (args: { event_id: string }) => {
      const cal = getCalendar();
      const e = await cal.events.get({
        calendarId: primaryCalendarId,
        eventId: args.event_id,
      });
      return {
        id: e.data.id,
        summary: e.data.summary,
        description: e.data.description,
        start: e.data.start?.dateTime ?? e.data.start?.date,
        end: e.data.end?.dateTime ?? e.data.end?.date,
        htmlLink: e.data.htmlLink,
        attendees: e.data.attendees?.map((a) => ({ email: a.email, responseStatus: a.responseStatus })),
      };
    },
  },

  calendar_create_event: {
    spec: {
      type: "function",
      function: {
        name: "calendar_create_event",
        description: "Create a calendar event. Use ISO datetimes for timed events.",
        parameters: {
          type: "object",
          properties: {
            summary: { type: "string" },
            start_iso: { type: "string", description: "ISO start datetime" },
            end_iso: { type: "string", description: "ISO end datetime" },
            description: { type: "string" },
          },
          required: ["summary", "start_iso", "end_iso"],
        },
      },
    },
    handler: async (args: {
      summary: string;
      start_iso: string;
      end_iso: string;
      description?: string;
    }) => {
      const cal = getCalendar();
      const created = await cal.events.insert({
        calendarId: primaryCalendarId,
        requestBody: {
          summary: args.summary,
          description: args.description,
          start: { dateTime: args.start_iso, timeZone: tz() },
          end: { dateTime: args.end_iso, timeZone: tz() },
        },
      });
      return {
        id: created.data.id,
        htmlLink: created.data.htmlLink,
        start: created.data.start?.dateTime,
        end: created.data.end?.dateTime,
      };
    },
  },

  calendar_update_event: {
    spec: {
      type: "function",
      function: {
        name: "calendar_update_event",
        description: "Patch an existing event (partial). Omit fields you do not change.",
        parameters: {
          type: "object",
          properties: {
            event_id: { type: "string" },
            summary: { type: "string" },
            start_iso: { type: "string" },
            end_iso: { type: "string" },
            description: { type: "string" },
          },
          required: ["event_id"],
        },
      },
    },
    handler: async (args: {
      event_id: string;
      summary?: string;
      start_iso?: string;
      end_iso?: string;
      description?: string;
    }) => {
      const cal = getCalendar();
      const current = await cal.events.get({
        calendarId: primaryCalendarId,
        eventId: args.event_id,
      });
      const body = current.data;
      if (args.summary !== undefined) body.summary = args.summary;
      if (args.description !== undefined) body.description = args.description;
      if (args.start_iso !== undefined) {
        body.start = { ...body.start, dateTime: args.start_iso, timeZone: tz() };
      }
      if (args.end_iso !== undefined) {
        body.end = { ...body.end, dateTime: args.end_iso, timeZone: tz() };
      }
      const updated = await cal.events.update({
        calendarId: primaryCalendarId,
        eventId: args.event_id,
        requestBody: body,
      });
      return {
        id: updated.data.id,
        htmlLink: updated.data.htmlLink,
        start: updated.data.start?.dateTime,
        end: updated.data.end?.dateTime,
      };
    },
  },

  calendar_delete_event: {
    spec: {
      type: "function",
      function: {
        name: "calendar_delete_event",
        description: "Delete a calendar event permanently.",
        parameters: {
          type: "object",
          properties: { event_id: { type: "string" } },
          required: ["event_id"],
        },
      },
    },
    handler: async (args: { event_id: string }) => {
      const cal = getCalendar();
      await cal.events.delete({
        calendarId: primaryCalendarId,
        eventId: args.event_id,
      });
      return { deleted: true, event_id: args.event_id };
    },
  },
};
