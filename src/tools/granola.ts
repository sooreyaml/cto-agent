import { granolaRequest } from "../integrations/granola.js";
import type { ToolDef } from "../agent/tool-types.js";

/**
 * Granola HTTP shapes vary by product version. These tools call REST paths you can align with Granola’s API.
 * Override GRANOLA_API_BASE; if calls 404, adjust paths in this file or in a fork.
 */
export const granolaTools: Record<string, ToolDef> = {
  granola_list_meetings: {
    spec: {
      type: "function",
      function: {
        name: "granola_list_meetings",
        description:
          "List recent meetings/notes from Granola API (GET /meetings?limit=). Path may need customization.",
        parameters: {
          type: "object",
          properties: {
            limit: { type: "integer" },
          },
        },
      },
    },
    handler: async (args: { limit?: number }) => {
      const lim = Math.min(args.limit ?? 10, 50);
      return granolaRequest(`/meetings?limit=${lim}`);
    },
  },

  granola_get_meeting: {
    spec: {
      type: "function",
      function: {
        name: "granola_get_meeting",
        description: "Fetch a single Granola meeting/note by id (GET /meetings/:id).",
        parameters: {
          type: "object",
          properties: { meeting_id: { type: "string" } },
          required: ["meeting_id"],
        },
      },
    },
    handler: async (args: { meeting_id: string }) => {
      return granolaRequest(`/meetings/${encodeURIComponent(args.meeting_id)}`);
    },
  },

  granola_search: {
    spec: {
      type: "function",
      function: {
        name: "granola_search",
        description: "Search Granola (GET /search?q=). Path may need customization for your workspace.",
        parameters: {
          type: "object",
          properties: {
            query: { type: "string" },
            limit: { type: "integer" },
          },
          required: ["query"],
        },
      },
    },
    handler: async (args: { query: string; limit?: number }) => {
      const lim = Math.min(args.limit ?? 10, 30);
      const q = encodeURIComponent(args.query);
      return granolaRequest(`/search?q=${q}&limit=${lim}`);
    },
  },
};
