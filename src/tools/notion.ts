import type { PageObjectResponse } from "@notionhq/client/build/src/api-endpoints.js";
import { isFullPage } from "@notionhq/client";
import { config } from "../config.js";
import { getNotion } from "../integrations/notion.js";
import type { ToolDef } from "../agent/tool-types.js";

/** Align these with your Notion DB property names. */
const P = {
  projectTitle: "Name",
  projectStatus: "Status",
  projectDeadline: "Deadline",
  taskTitle: "Name",
  taskDue: "Due",
  taskStatus: "Status",
  taskProject: "Project",
} as const;

function requireProjectsDb() {
  if (!config.NOTION_PROJECTS_DB_ID) throw new Error("NOTION_PROJECTS_DB_ID not configured");
}

function requireTasksDb() {
  if (!config.NOTION_TASKS_DB_ID) throw new Error("NOTION_TASKS_DB_ID not configured");
}

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
      return title.map((t: { plain_text: string }) => t.plain_text).join("") || "Untitled";
    }
  }
  return "Untitled";
}

function mapProjectRow(page: PageObjectResponse) {
  const props = page.properties;
  const name = titleFromPage(page);
  let status = "";
  const st = props[P.projectStatus];
  if (st?.type === "status") status = st.status?.name ?? "";
  let deadline: string | null = null;
  const dl = props[P.projectDeadline];
  if (dl?.type === "date") deadline = dl.date?.start ?? null;
  return { id: page.id, name, status, deadline, url: page.url };
}

function mapTaskRow(page: PageObjectResponse) {
  const props = page.properties;
  const name = titleFromPage(page);
  let status = "";
  const st = props[P.taskStatus];
  if (st?.type === "status") status = st.status?.name ?? "";
  let due: string | null = null;
  const d = props[P.taskDue];
  if (d?.type === "date") due = d.date?.start ?? null;
  let projectId: string | null = null;
  const rel = props[P.taskProject];
  if (rel?.type === "relation" && rel.relation[0]) projectId = rel.relation[0].id;
  return { id: page.id, name, status, due, projectPageId: projectId, url: page.url };
}

function mapPages(results: unknown[]) {
  return results
    .filter((r): r is PageObjectResponse => isFullPage(r as Parameters<typeof isFullPage>[0]))
    .map((p) => mapProjectRow(p));
}

function mapTaskPages(results: unknown[]) {
  return results
    .filter((r): r is PageObjectResponse => isFullPage(r as Parameters<typeof isFullPage>[0]))
    .map((p) => mapTaskRow(p));
}

export const notionTools: Record<string, ToolDef> = {
  notion_search_projects: {
    spec: {
      type: "function",
      function: {
        name: "notion_search_projects",
        description:
          "Search projects in the Projects Notion database. Returns projects with Name, Status, Deadline, page ID. Optional status filter.",
        parameters: {
          type: "object",
          properties: {
            status: { type: "string", description: "Optional status name to filter (exact)" },
            limit: { type: "integer", description: "Max results (default 20)" },
          },
        },
      },
    },
    handler: async (args: { status?: string; limit?: number }) => {
      requireProjectsDb();
      const notion = getNotion();
      const filter = args.status
        ? { property: P.projectStatus, status: { equals: args.status } }
        : undefined;
      const res = await notion.databases.query({
        database_id: config.NOTION_PROJECTS_DB_ID,
        filter: filter as never,
        page_size: Math.min(args.limit ?? 20, 100),
      });
      return mapPages(res.results);
    },
  },

  notion_create_project: {
    spec: {
      type: "function",
      function: {
        name: "notion_create_project",
        description: "Create a new project page in the Projects database.",
        parameters: {
          type: "object",
          properties: {
            name: { type: "string", description: "Project title" },
            status: { type: "string", description: "Status option name (must exist in Notion)" },
            deadline: { type: "string", description: "ISO date YYYY-MM-DD or empty" },
          },
          required: ["name"],
        },
      },
    },
    handler: async (args: { name: string; status?: string; deadline?: string }) => {
      requireProjectsDb();
      const notion = getNotion();
      const props: Record<string, unknown> = {
        [P.projectTitle]: {
          title: [{ text: { content: args.name } }],
        },
      };
      if (args.status) {
        props[P.projectStatus] = { status: { name: args.status } };
      }
      if (args.deadline) {
        props[P.projectDeadline] = { date: { start: args.deadline } };
      }
      const created = await notion.pages.create({
        parent: { database_id: config.NOTION_PROJECTS_DB_ID },
        properties: props as never,
      });
      if (!isFullPage(created)) return { id: created.id, url: (created as { url?: string }).url };
      return mapProjectRow(created);
    },
  },

  notion_update_project: {
    spec: {
      type: "function",
      function: {
        name: "notion_update_project",
        description: "Update an existing project Notion page by page ID.",
        parameters: {
          type: "object",
          properties: {
            page_id: { type: "string", description: "Notion page UUID" },
            name: { type: "string" },
            status: { type: "string" },
            deadline: { type: "string", description: "YYYY-MM-DD or empty to clear" },
          },
          required: ["page_id"],
        },
      },
    },
    handler: async (args: { page_id: string; name?: string; status?: string; deadline?: string }) => {
      requireProjectsDb();
      const notion = getNotion();
      const props: Record<string, unknown> = {};
      if (args.name !== undefined) {
        props[P.projectTitle] = { title: [{ text: { content: args.name } }] };
      }
      if (args.status !== undefined) {
        props[P.projectStatus] = { status: { name: args.status } };
      }
      if (args.deadline !== undefined) {
        props[P.projectDeadline] = args.deadline
          ? { date: { start: args.deadline } }
          : { date: null };
      }
      const updated = await notion.pages.update({
        page_id: args.page_id,
        properties: props as never,
      });
      if (!isFullPage(updated)) return { id: updated.id, ok: true };
      return mapProjectRow(updated);
    },
  },

  notion_search_tasks: {
    spec: {
      type: "function",
      function: {
        name: "notion_search_tasks",
        description: "Search tasks in the Tasks Notion database.",
        parameters: {
          type: "object",
          properties: {
            status: { type: "string", description: "Optional status filter" },
            limit: { type: "integer" },
          },
        },
      },
    },
    handler: async (args: { status?: string; limit?: number }) => {
      requireTasksDb();
      const notion = getNotion();
      const filter = args.status
        ? { property: P.taskStatus, status: { equals: args.status } }
        : undefined;
      const res = await notion.databases.query({
        database_id: config.NOTION_TASKS_DB_ID,
        filter: filter as never,
        page_size: Math.min(args.limit ?? 20, 100),
      });
      return mapTaskPages(res.results);
    },
  },

  notion_create_task: {
    spec: {
      type: "function",
      function: {
        name: "notion_create_task",
        description: "Create a task in the Tasks database. Optionally link to a project page ID.",
        parameters: {
          type: "object",
          properties: {
            title: { type: "string" },
            due: { type: "string", description: "YYYY-MM-DD" },
            status: { type: "string" },
            project_page_id: { type: "string", description: "Parent project Notion page UUID" },
          },
          required: ["title"],
        },
      },
    },
    handler: async (args: {
      title: string;
      due?: string;
      status?: string;
      project_page_id?: string;
    }) => {
      requireTasksDb();
      const notion = getNotion();
      const props: Record<string, unknown> = {
        [P.taskTitle]: {
          title: [{ text: { content: args.title } }],
        },
      };
      if (args.due) props[P.taskDue] = { date: { start: args.due } };
      if (args.status) props[P.taskStatus] = { status: { name: args.status } };
      if (args.project_page_id) {
        props[P.taskProject] = { relation: [{ id: args.project_page_id }] };
      }
      const created = await notion.pages.create({
        parent: { database_id: config.NOTION_TASKS_DB_ID },
        properties: props as never,
      });
      if (!isFullPage(created)) return { id: created.id };
      return mapTaskRow(created);
    },
  },

  notion_update_task: {
    spec: {
      type: "function",
      function: {
        name: "notion_update_task",
        description: "Update a task page by ID.",
        parameters: {
          type: "object",
          properties: {
            page_id: { type: "string" },
            title: { type: "string" },
            due: { type: "string" },
            status: { type: "string" },
            project_page_id: { type: "string", description: "Set or replace project relation" },
          },
          required: ["page_id"],
        },
      },
    },
    handler: async (args: {
      page_id: string;
      title?: string;
      due?: string;
      status?: string;
      project_page_id?: string;
    }) => {
      requireTasksDb();
      const notion = getNotion();
      const props: Record<string, unknown> = {};
      if (args.title !== undefined) {
        props[P.taskTitle] = { title: [{ text: { content: args.title } }] };
      }
      if (args.due !== undefined) {
        props[P.taskDue] = args.due ? { date: { start: args.due } } : { date: null };
      }
      if (args.status !== undefined) {
        props[P.taskStatus] = { status: { name: args.status } };
      }
      if (args.project_page_id !== undefined) {
        props[P.taskProject] = { relation: [{ id: args.project_page_id }] };
      }
      const updated = await notion.pages.update({
        page_id: args.page_id,
        properties: props as never,
      });
      if (!isFullPage(updated)) return { id: updated.id, ok: true };
      return mapTaskRow(updated);
    },
  },
};
