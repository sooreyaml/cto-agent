import { Octokit } from "octokit";
import { config } from "../config.js";

export function getOctokit(): Octokit {
  if (!config.GITHUB_PAT) throw new Error("GITHUB_PAT not configured");
  return new Octokit({ auth: config.GITHUB_PAT });
}
