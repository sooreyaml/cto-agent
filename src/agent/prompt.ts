import fs from "node:fs";
import path from "node:path";
import { config } from "../config.js";
import { logger } from "../utils/logger.js";

const CALENDAR_PLACEHOLDER = "{{CALENDAR_CONTEXT}}";

/** Wall-clock "today" in the user's timezone, for every request (avoids invented dates). */
function currentCalendarContext(): string {
  const now = new Date();
  const long = new Intl.DateTimeFormat("en-GB", {
    timeZone: config.TIMEZONE,
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(now);
  const iso = new Intl.DateTimeFormat("en-CA", {
    timeZone: config.TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
  return `Today (authoritative for this chat turn, ${config.TIMEZONE}) is ${long} — calendar date *${iso}*. Use only this when the user asks about "today", weekends, or due dates; do not guess another year or day.`;
}

/** Used only if `SYSTEM_PROMPT_PATH` file is missing (misconfigured deploy). */
function fallbackSystemTemplate(): string {
  return [
    "You are CTO Agent, a concise technical chief-of-staff assistant in Slack.",
    CALENDAR_PLACEHOLDER,
    "Prefer short answers; use bullets when listing items.",
    "Formatting: this text is shown with Slack mrkdwn. Use *bold* with single asterisks only (never **). _italic_ uses underscores.",
    "Do not use # / ## headings. Do not use --- horizontal rules (they show as raw text). Separate sections with a blank line and a *Section title* line instead.",
    "Links: <https://example.com|short label>. Inline code: single `backticks` (no language fences for short snippets).",
    "Notion: use notion_describe_tasks_database to list allowed Status option names; use notion_search_tasks / notion_create_task / notion_update_task for tasks (NOTION_TASKS_DB_ID). If project tools exist, they use a separate projects database.",
    "Reminders: slack_remind_at schedules a DM via Slack scheduled messages (not /remind). slack_list_reminders / slack_cancel_reminder to manage. Requires the workspace app token to have permission to post in your DM.",
    "Use tools when the user asks for live data. For destructive actions (send email, delete calendar events) require explicit confirmation first.",
    "If a tool is not configured, say so briefly and proceed with what you can.",
    "The user may attach images; describe what you see and use that context in your answer.",
  ].join("\n");
}

function loadSystemTemplate(): string {
  const raw = config.SYSTEM_PROMPT_PATH.trim();
  const resolved = path.isAbsolute(raw) ? raw : path.join(process.cwd(), raw);
  try {
    return fs.readFileSync(resolved, "utf8");
  } catch (err) {
    logger.warn(
      { err, resolved },
      "SYSTEM_PROMPT file missing; using built-in fallback (fix path or add file)",
    );
    return fallbackSystemTemplate();
  }
}

export function buildSystemPrompt(): string {
  const template = loadSystemTemplate();
  const calendar = currentCalendarContext();
  if (template.includes(CALENDAR_PLACEHOLDER)) {
    return template.split(CALENDAR_PLACEHOLDER).join(calendar).trim();
  }
  return `${template.trim()}\n\n${calendar}`.trim();
}
