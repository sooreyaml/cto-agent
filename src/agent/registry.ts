import { notionTools } from "../tools/notion.js";
import { gmailTools } from "../tools/gmail.js";
import { calendarTools } from "../tools/calendar.js";
import { githubTools } from "../tools/github.js";
import { granolaTools } from "../tools/granola.js";
import type { ToolDef, ToolHandler } from "./tool-types.js";

const allTools: Record<string, ToolDef> = {
  ...notionTools,
  ...gmailTools,
  ...calendarTools,
  ...githubTools,
  ...granolaTools,
};

export const toolRegistry: Record<string, ToolHandler> = Object.fromEntries(
  Object.entries(allTools).map(([k, v]) => [k, v.handler])
);

export const toolSpecs = Object.values(allTools).map((t) => t.spec);

export type { ToolDef, ToolHandler, ToolSpec } from "./tool-types.js";
