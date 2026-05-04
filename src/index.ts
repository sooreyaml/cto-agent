import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { config } from "./config.js";
import { logger } from "./utils/logger.js";
import { healthRoutes } from "./routes/health.js";
import { slackRoutes } from "./routes/slack.js";
import { cronRoutes } from "./routes/cron.js";

const app = new Hono();

app.route("/healthz", healthRoutes);
app.route("/slack", slackRoutes);
app.route("/cron", cronRoutes);

serve(
  {
    fetch: app.fetch,
    port: config.PORT,
  },
  (info) => {
    logger.info({ port: info.port, env: config.NODE_ENV }, "server listening");
  }
);
