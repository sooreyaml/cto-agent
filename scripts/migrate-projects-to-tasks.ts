/**
 * One-way copy: each row in NOTION_PROJECTS_DB_ID → one page in NOTION_TASKS_DB_ID.
 *
 * Maps: project Name → task Name, Status, Deadline → Due, and links Project relation
 * to the original project page (when that column exists on the tasks DB).
 *
 * Usage (from repo root, with a valid `.env`):
 *   pnpm run notion:migrate-projects-to-tasks
 *   pnpm run notion:migrate-projects-to-tasks -- --dry-run
 *
 * Requires task columns matching the agent defaults (see `src/tools/notion.ts`): Name, Due, Status, Project (relation).
 */

import "dotenv/config";
import { isFullPage } from "@notionhq/client";
import { getNotion } from "../src/integrations/notion.js";
import { config } from "../src/config.js";
import {
  extractProjectBriefFields,
} from "../src/lib/notion-project-fields.js";

const TASK_NAME = "Name";
const TASK_DUE = "Due";
const TASK_STATUS = "Status";
const TASK_PROJECT = "Project";

function taskStatusWritePayload(
  taskStatusType: "select" | "status",
  name: string,
): { select: { name: string } } | { status: { name: string } } {
  if (taskStatusType === "select") return { select: { name } };
  return { status: { name } };
}

function argsHas(flag: string) {
  return process.argv.includes(flag);
}

function taskTitleFromBrief(name: string): string {
  return name || "Untitled";
}

async function taskAlreadyLinked(
  notion: ReturnType<typeof getNotion>,
  projectPageId: string,
  schemaHasProject: boolean,
): Promise<boolean> {
  if (!schemaHasProject) return false;
  try {
    const res = await notion.databases.query({
      database_id: config.NOTION_TASKS_DB_ID,
      filter: { property: TASK_PROJECT, relation: { contains: projectPageId } },
      page_size: 1,
    });
    return res.results.length > 0;
  } catch {
    return false;
  }
}

async function main() {
  const dryRun = argsHas("--dry-run");
  const force = argsHas("--force");

  if (!config.NOTION_TOKEN) {
    console.error("NOTION_TOKEN is required");
    process.exit(1);
  }
  if (!config.NOTION_PROJECTS_DB_ID || !config.NOTION_TASKS_DB_ID) {
    console.error("NOTION_PROJECTS_DB_ID and NOTION_TASKS_DB_ID are required");
    process.exit(1);
  }

  const notion = getNotion();
  const tasksMeta = await notion.databases.retrieve({
    database_id: config.NOTION_TASKS_DB_ID,
  });
  const props = tasksMeta.properties;
  const hasTitle = Object.entries(props).some(
    ([name, p]) => name === TASK_NAME && p.type === "title",
  );
  if (!hasTitle) {
    console.error(
      `Tasks database must have a title property named "${TASK_NAME}" (or rename it in this script).`,
    );
    process.exit(1);
  }
  const taskStatusProp = props[TASK_STATUS];
  const taskStatusType =
    taskStatusProp?.type === "select" || taskStatusProp?.type === "status"
      ? taskStatusProp.type
      : null;
  const hasStatus = taskStatusType !== null;
  const hasDue = props[TASK_DUE]?.type === "date";
  const hasProjectRel = props[TASK_PROJECT]?.type === "relation";

  let cursor: string | undefined;
  let created = 0;
  let skipped = 0;
  let failed = 0;

  do {
    const res = await notion.databases.query({
      database_id: config.NOTION_PROJECTS_DB_ID,
      start_cursor: cursor,
      page_size: 100,
    });

    for (const row of res.results) {
      if (!isFullPage(row)) continue;
      const brief = extractProjectBriefFields(row);
      const title = taskTitleFromBrief(brief.name);

      if (
        !force &&
        (await taskAlreadyLinked(notion, row.id, hasProjectRel))
      ) {
        skipped++;
        console.log(`skip (already linked): ${brief.name}`);
        continue;
      }

      const pageProps: Record<string, unknown> = {
        [TASK_NAME]: {
          title: [{ text: { content: title } }],
        },
      };
      if (hasDue && brief.deadline) {
        pageProps[TASK_DUE] = { date: { start: brief.deadline } };
      }
      if (hasStatus && taskStatusType && brief.status) {
        pageProps[TASK_STATUS] = taskStatusWritePayload(
          taskStatusType,
          brief.status,
        );
      }
      if (hasProjectRel) {
        pageProps[TASK_PROJECT] = { relation: [{ id: row.id }] };
      }

      if (dryRun) {
        console.log(`[dry-run] would create task: ${title}`);
        created++;
        continue;
      }

      try {
        await notion.pages.create({
          parent: { database_id: config.NOTION_TASKS_DB_ID },
          properties: pageProps as never,
        });
        created++;
        console.log(`created: ${title}`);
      } catch (err) {
        failed++;
        const msg = err instanceof Error ? err.message : String(err);
        console.error(`failed: ${brief.name} — ${msg}`);
      }
    }

    cursor = res.has_more ? res.next_cursor ?? undefined : undefined;
  } while (cursor);

  console.log(
    `\nDone. ${dryRun ? "Planned" : "Created"}: ${created}, skipped: ${skipped}, failed: ${failed}`,
  );
  if (!hasProjectRel) {
    console.warn(
      `Note: no "${TASK_PROJECT}" relation column on tasks DB — tasks are not linked back to projects.`,
    );
  }
  if (!hasDue) {
    console.warn(`Note: no "${TASK_DUE}" date column — due dates were not copied.`);
  }
  if (!hasStatus) {
    console.warn(`Note: no "${TASK_STATUS}" column — status was not copied.`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
