import "dotenv/config";
import { z } from "zod";

const envSchema = z.object({
  PORT: z.coerce.number().default(3000),
  NODE_ENV: z.enum(["development", "production", "test"]).default("development"),
  LOG_LEVEL: z.string().default("info"),
  TIMEZONE: z.string().default("Europe/London"),
  APP_PUBLIC_URL: z.string().min(1).default("http://localhost:3000"),

  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),

  OPENROUTER_API_KEY: z.string().min(1, "OPENROUTER_API_KEY is required"),
  OPENROUTER_MODEL: z.string().default("anthropic/claude-sonnet-4.6"),
  OPENROUTER_BASE_URL: z.string().url().default("https://openrouter.ai/api/v1"),

  SLACK_BOT_TOKEN: z.string().min(1, "SLACK_BOT_TOKEN is required"),
  SLACK_SIGNING_SECRET: z.string().min(1, "SLACK_SIGNING_SECRET is required"),
  SLACK_USER_ID: z.string().min(1, "SLACK_USER_ID is required"),

  NOTION_TOKEN: z.string().optional().default(""),
  NOTION_PROJECTS_DB_ID: z.string().optional().default(""),
  NOTION_TASKS_DB_ID: z.string().optional().default(""),
  NOTION_LOGS_DB_ID: z.string().optional().default(""),

  GOOGLE_CLIENT_ID: z.string().optional().default(""),
  GOOGLE_CLIENT_SECRET: z.string().optional().default(""),
  GOOGLE_REFRESH_TOKEN: z.string().optional().default(""),
  GOOGLE_USER_EMAIL: z.string().optional().default(""),

  GITHUB_PAT: z.string().optional().default(""),
  GITHUB_USERNAME: z.string().optional().default(""),
  /** Comma-separated `owner/repo` for daily brief + optional defaults for GitHub tools. */
  GITHUB_BRIEF_REPOS: z.string().optional().default(""),

  GRANOLA_API_BASE: z.string().url().default("https://api.granola.ai"),
  GRANOLA_API_KEY: z.string().optional().default(""),

  CRON_SECRET: z.string().optional().default(""),
});

export type Config = z.infer<typeof envSchema>;

export const config: Config = envSchema.parse(process.env);
