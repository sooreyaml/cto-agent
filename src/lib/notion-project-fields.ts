import type { PageObjectResponse } from "@notionhq/client/build/src/api-endpoints.js";
import { config } from "../config.js";

/**
 * Notion project database property names (case-sensitive). Adjust if yours differ.
 */
export const PROJECT_PROPS = {
  title: "Name",
  status: "Status",
  deadline: "Deadline",
  priority: "Priority",
  currentFocus: "Current focus",
  nextAction: "Next action",
} as const;

export type ProjectBriefFields = {
  name: string;
  status: string;
  priority: string;
  currentFocus: string;
  nextAction: string;
  deadline: string | null;
};

function readRichText(prop: unknown): string {
  if (!prop || typeof prop !== "object" || !("type" in prop)) return "";
  const p = prop as {
    type: string;
    rich_text?: { plain_text: string }[];
    title?: { plain_text: string }[];
  };
  if (p.type === "rich_text" && Array.isArray(p.rich_text)) {
    return p.rich_text.map((t) => t.plain_text).join("");
  }
  if (p.type === "title" && Array.isArray(p.title)) {
    return p.title.map((t) => t.plain_text).join("");
  }
  return "";
}

function readPriority(prop: unknown): string {
  if (!prop || typeof prop !== "object" || !("type" in prop)) return "";
  const p = prop as {
    type: string;
    select?: { name: string } | null;
    status?: { name: string } | null;
    number?: number | null;
    rich_text?: { plain_text: string }[];
  };
  if (p.type === "select") return p.select?.name ?? "";
  if (p.type === "status") return p.status?.name ?? "";
  if (p.type === "number" && p.number != null && !Number.isNaN(p.number)) return String(p.number);
  if (p.type === "rich_text" && p.rich_text) {
    return p.rich_text.map((t) => t.plain_text).join("");
  }
  return "";
}

function titleFromPage(page: PageObjectResponse, titlePropName: string): string {
  const named = page.properties[titlePropName];
  if (named?.type === "title") {
    return named.title.map((t) => t.plain_text).join("") || "Untitled";
  }
  for (const [, prop] of Object.entries(page.properties)) {
    if (
      prop &&
      typeof prop === "object" &&
      "type" in prop &&
      prop.type === "title" &&
      "title" in prop
    ) {
      const title = (prop as { title: { plain_text: string }[] }).title;
      return title.map((t) => t.plain_text).join("") || "Untitled";
    }
  }
  return "Untitled";
}

/** Plain-text snapshot for briefs, tools, and LLM context (no Notion URLs). */
export function extractProjectBriefFields(page: PageObjectResponse): ProjectBriefFields {
  const props = page.properties;
  let status = "";
  const st = props[PROJECT_PROPS.status];
  if (st?.type === "status") status = st.status?.name ?? "";
  else if (st?.type === "select") status = st.select?.name ?? "";

  let deadline: string | null = null;
  const dl = props[PROJECT_PROPS.deadline];
  if (dl?.type === "date") deadline = dl.date?.start ?? null;

  return {
    name: titleFromPage(page, PROJECT_PROPS.title),
    status,
    priority: readPriority(props[PROJECT_PROPS.priority]),
    currentFocus: readRichText(props[PROJECT_PROPS.currentFocus]),
    nextAction: readRichText(props[PROJECT_PROPS.nextAction]),
    deadline,
  };
}

/** Database query filter for Status / single-select by kind from env. */
export function notionStatusDbFilter(
  propertyName: string,
  equals: string
): { property: string; select: { equals: string } } | { property: string; status: { equals: string } } {
  if (config.NOTION_STATUS_PROPERTY_KIND === "select") {
    return { property: propertyName, select: { equals } };
  }
  return { property: propertyName, status: { equals } };
}

/** `pages.create` / `pages.update` payload for status or select column. */
export function notionStatusUpdatePayload(name: string) {
  if (config.NOTION_STATUS_PROPERTY_KIND === "select") {
    return { select: { name } };
  }
  return { status: { name } };
}

export function notionStatusClearPayload() {
  if (config.NOTION_STATUS_PROPERTY_KIND === "select") {
    return { select: null };
  }
  return { status: null };
}
