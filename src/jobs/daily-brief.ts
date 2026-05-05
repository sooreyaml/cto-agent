import { isFullPage } from "@notionhq/client";
import { config } from "../config.js";
import { llm, MODEL } from "../agent/llm.js";
import { getNotion } from "../integrations/notion.js";
import { getGmail, getCalendar } from "../integrations/google.js";
import { getOctokit } from "../integrations/github.js";
import { granolaRequest } from "../integrations/granola.js";
import { postDmToUser } from "../integrations/slack.js";
import { logger } from "../utils/logger.js";

async function safe<T>(
  label: string,
  fn: () => Promise<T>
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  try {
    const data = await fn();
    return { ok: true, data };
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    logger.warn({ err, label }, "daily brief source failed");
    return { ok: false, error };
  }
}

export async function runDailyBrief(): Promise<void> {
  const notionPart = await safe("notion", async () => {
    if (!config.NOTION_TOKEN || !config.NOTION_PROJECTS_DB_ID) return { skipped: true as const };
    const notion = getNotion();
    const res = await notion.databases.query({
      database_id: config.NOTION_PROJECTS_DB_ID,
      page_size: 15,
    });
    const rows: { name: string; status: string; url: string }[] = [];
    for (const r of res.results) {
      if (!isFullPage(r)) continue;
      let name = "";
      for (const prop of Object.values(r.properties)) {
        if (prop.type === "title") {
          name = prop.title.map((t) => t.plain_text).join("");
          break;
        }
      }
      let status = "";
      const st = r.properties.Status;
      if (st?.type === "status") status = st.status?.name ?? "";
      rows.push({ name, status, url: r.url });
    }
    return rows;
  });

  const calendarPart = await safe("calendar", async () => {
    if (!config.GOOGLE_REFRESH_TOKEN) return { skipped: true as const };
    const cal = getCalendar();
    const now = new Date();
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    const res = await cal.events.list({
      calendarId: "primary",
      timeMin: start.toISOString(),
      timeMax: end.toISOString(),
      singleEvents: true,
      orderBy: "startTime",
      timeZone: config.TIMEZONE,
      maxResults: 40,
    });
    return (res.data.items ?? []).map((e) => ({
      summary: e.summary,
      start: e.start?.dateTime ?? e.start?.date,
      htmlLink: e.htmlLink,
    }));
  });

  const gmailPart = await safe("gmail", async () => {
    if (!config.GOOGLE_REFRESH_TOKEN) return { skipped: true as const };
    const gmail = getGmail();
    const list = await gmail.users.messages.list({
      userId: "me",
      q: "is:unread newer_than:7d",
      maxResults: 8,
    });
    const ids = list.data.messages?.map((m) => m.id!).filter(Boolean) ?? [];
    const items: { subject?: string; from?: string; snippet?: string }[] = [];
    for (const id of ids) {
      const msg = await gmail.users.messages.get({
        userId: "me",
        id,
        format: "metadata",
        metadataHeaders: ["Subject", "From"],
      });
      const headers = msg.data.payload?.headers ?? [];
      items.push({
        subject: headers.find((h) => h.name?.toLowerCase() === "subject")?.value ?? undefined,
        from: headers.find((h) => h.name?.toLowerCase() === "from")?.value ?? undefined,
        snippet: msg.data.snippet ?? undefined,
      });
    }
    return items;
  });

  const githubPart = await safe("github", async () => {
    if (!config.GITHUB_PAT || !config.GITHUB_BRIEF_REPOS.trim()) return { skipped: true as const };
    const octokit = getOctokit();
    const specs = config.GITHUB_BRIEF_REPOS.split(",").map((s) => s.trim()).filter(Boolean);
    const out: {
      repo: string;
      open_prs: { title: string; url: string }[];
      recent_failed_runs: { name: string | undefined; url: string | undefined }[];
    }[] = [];
    for (const spec of specs) {
      const [owner, repo] = spec.split("/");
      if (!owner || !repo) continue;
      const prs = await octokit.rest.pulls.list({
        owner,
        repo,
        state: "open",
        per_page: 8,
      });
      const runs = await octokit.rest.actions.listWorkflowRunsForRepo({
        owner,
        repo,
        branch: "main",
        per_page: 8,
      });
      const failing = (runs.data.workflow_runs ?? []).filter((r) => r.conclusion === "failure");
      out.push({
        repo: spec,
        open_prs: prs.data.map((p) => ({ title: p.title, url: p.html_url })),
        recent_failed_runs: failing.slice(0, 4).map((r) => ({
          name: r.name ?? undefined,
          url: r.html_url ?? undefined,
        })),
      });
    }
    return out;
  });

  const granolaPart = await safe("granola", async () => {
    if (!config.GRANOLA_API_KEY) return { skipped: true as const };
    return granolaRequest("/meetings?limit=5");
  });

  const bundle = {
    date: new Date().toISOString(),
    timezone: config.TIMEZONE,
    notion: notionPart,
    calendar: calendarPart,
    gmail: gmailPart,
    github: githubPart,
    granola: granolaPart,
  };

  const completion = await llm.chat.completions.create({
    model: MODEL,
    messages: [
      {
        role: "system",
        content: [
          "You write a short daily executive brief for Slack.",
          "Use short headings and bullets. Include sections only when you have data:",
          "**Today** (calendar), **Inbox** (Gmail), **Code** (GitHub PRs and failed runs), **Projects** (Notion).",
          "If a source was skipped or errored, omit that section or say one line. Stay under ~800 words.",
        ].join(" "),
      },
      { role: "user", content: JSON.stringify(bundle) },
    ],
    temperature: 0.35,
    max_tokens: 2048,
  });

  const text = completion.choices[0]?.message?.content?.trim();
  if (!text) {
    logger.error("daily brief: empty LLM output");
    return;
  }

  await postDmToUser(config.SLACK_USER_ID, text);
  logger.info("daily brief sent");
}
