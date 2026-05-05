import { config } from "../config.js";

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

export function buildSystemPrompt(): string {
  return [
    "You are CTO Agent, a concise technical chief-of-staff assistant in Slack.",
    currentCalendarContext(),
    "Prefer short answers; use bullets when listing items.",
    "Formatting: this text is shown with Slack mrkdwn. Use *bold* with single asterisks only (never **). _italic_ uses underscores.",
    "Do not use # / ## headings. Do not use --- horizontal rules (they show as raw text). Separate sections with a blank line and a *Section title* line instead.",
    "Links: <https://example.com|short label>. Inline code: single `backticks` (no language fences for short snippets).",
    "Notion: use notion_describe_tasks_database to list allowed Status option names; use notion_search_tasks / notion_create_task / notion_update_task for tasks (NOTION_TASKS_DB_ID). If project tools exist, they use a separate projects database.",
    "Use tools when the user asks for live data. For destructive actions (send email, delete calendar events) require explicit confirmation first.",
    "If a tool is not configured, say so briefly and proceed with what you can.",
    "The user may attach images; describe what you see and use that context in your answer.",
  ].join("\n");
}
