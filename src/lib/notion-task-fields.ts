import type { PageObjectResponse } from "@notionhq/client/build/src/api-endpoints.js";

/**
 * Task database property names (case-sensitive). Match your Notion DB after converting
 * from projects: if Notion renamed "Deadline" → keep `due` as the actual column name.
 */
export const TASK_PROPS = {
  title: "Name",
  due: "Due",
  status: "Status",
  project: "Project",
} as const;

export type TaskRowBrief = {
  id: string;
  name: string;
  status: string;
  due: string | null;
  projectPageId: string | null;
  url: string;
};

function titleFromPage(page: PageObjectResponse): string {
  for (const [, prop] of Object.entries(page.properties)) {
    if (
      prop &&
      typeof prop === "object" &&
      "type" in prop &&
      prop.type === "title" &&
      "title" in prop &&
      Array.isArray((prop as { title: { plain_text: string }[] }).title)
    ) {
      const title = (prop as { title: { plain_text: string }[] }).title;
      return (
        title.map((t: { plain_text: string }) => t.plain_text).join("") ||
        "Untitled"
      );
    }
  }
  return "Untitled";
}

export function mapTaskRow(page: PageObjectResponse): TaskRowBrief {
  const props = page.properties;
  const name = titleFromPage(page);
  let status = "";
  const st = props[TASK_PROPS.status];
  if (st?.type === "status") status = st.status?.name ?? "";
  else if (st?.type === "select") status = st.select?.name ?? "";
  let due: string | null = null;
  const d = props[TASK_PROPS.due];
  if (d?.type === "date") due = d.date?.start ?? null;
  let projectPageId: string | null = null;
  const rel = props[TASK_PROPS.project];
  if (rel?.type === "relation" && rel.relation[0])
    projectPageId = rel.relation[0].id;
  return { id: page.id, name, status, due, projectPageId, url: page.url };
}
