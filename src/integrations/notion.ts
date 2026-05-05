import { Client } from "@notionhq/client";

import { config } from "../config.js";

export function getNotion(): Client {
  if (!config.NOTION_TOKEN) throw new Error("NOTION_TOKEN not configured");
  return new Client({ auth: config.NOTION_TOKEN, notionVersion: "2022-06-28" });
}
