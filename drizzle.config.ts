import { defineConfig } from "drizzle-kit";

export default defineConfig({
  schema: "./src/memory/schema.ts",
  out: "./drizzle/migrations",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "",
  },
});
