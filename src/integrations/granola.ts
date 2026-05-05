import { config } from "../config.js";

/** Generic JSON HTTP helper; set GRANOLA_API_BASE to Granola’s API root per their docs. */
export async function granolaRequest(path: string, init?: RequestInit): Promise<unknown> {
  if (!config.GRANOLA_API_KEY) throw new Error("GRANOLA_API_KEY not configured");
  const base = config.GRANOLA_API_BASE.replace(/\/$/, "");
  const url = path.startsWith("http") ? path : `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${config.GRANOLA_API_KEY}`);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const res = await fetch(url, { ...init, headers });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Granola ${res.status}: ${text.slice(0, 300)}`);
  }
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}
