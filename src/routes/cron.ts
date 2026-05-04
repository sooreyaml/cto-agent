import { Hono } from "hono";
import { config } from "../config.js";
import { dispatchDetached } from "../utils/dispatch.js";
import { runDailyBrief } from "../jobs/daily-brief.js";

export const cronRoutes = new Hono();

cronRoutes.get("/health", (c) => c.json({ ok: true, cron: "up" }));

cronRoutes.post("/daily-brief", async (c) => {
  if (!config.CRON_SECRET) {
    return c.json({ error: "CRON_SECRET not configured" }, 503);
  }
  const auth = c.req.header("authorization");
  if (auth !== `Bearer ${config.CRON_SECRET}`) {
    return c.text("Unauthorized", 401);
  }
  dispatchDetached("daily-brief", () => runDailyBrief());
  return c.json({ ok: true, dispatched: true });
});
