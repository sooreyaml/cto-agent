import { config } from "../config.js";
import { notionTools } from "../tools/notion.js";
import { gmailTools } from "../tools/gmail.js";
import { calendarTools } from "../tools/calendar.js";
import { githubTools } from "../tools/github.js";
import { granolaTools } from "../tools/granola.js";
import type { ToolDef, ToolHandler } from "./tool-types.js";

const PROJECT_NOTION_TOOLS = new Set([
  "notion_search_projects",
  "notion_create_project",
  "notion_update_project",
]);

const TASK_NOTION_TOOLS = new Set([
  "notion_search_tasks",
  "notion_create_task",
  "notion_update_task",
]);

function activeNotionTools(): Record<string, ToolDef> {
  return Object.fromEntries(
    Object.entries(notionTools).filter(([name]) => {
      if (PROJECT_NOTION_TOOLS.has(name)) {
        return Boolean(config.NOTION_PROJECTS_DB_ID);
      }
      if (TASK_NOTION_TOOLS.has(name)) {
        return Boolean(config.NOTION_TASKS_DB_ID);
      }
      return true;
    }),
  ) as Record<string, ToolDef>;
}

const allTools: Record<string, ToolDef> = {
  ...activeNotionTools(),
  ...gmailTools,
  ...calendarTools,
  ...githubTools,
  ...granolaTools,
};

export const toolRegistry: Record<string, ToolHandler> = Object.fromEntries(
  Object.entries(allTools).map(([k, v]) => [k, v.handler]),
);

export const toolSpecs = Object.values(allTools).map((t) => t.spec);

export type { ToolDef, ToolHandler, ToolSpec } from "./tool-types.js";
