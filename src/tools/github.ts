import { getOctokit } from "../integrations/github.js";
import { config } from "../config.js";
import type { ToolDef } from "../agent/tool-types.js";

function parseRepo(owner: string | undefined, repo: string | undefined): { owner: string; repo: string } {
  const o = owner?.trim();
  const r = repo?.trim();
  if (o && r) return { owner: o, repo: r };
  const def = config.GITHUB_BRIEF_REPOS.split(",")[0]?.trim();
  if (def?.includes("/")) {
    const [oo, rr] = def.split("/");
    if (oo && rr) return { owner: oo, repo: rr };
  }
  if (config.GITHUB_USERNAME && r) return { owner: config.GITHUB_USERNAME, repo: r };
  throw new Error("Provide owner and repo, or set GITHUB_BRIEF_REPOS=owner/repo");
}

export const githubTools: Record<string, ToolDef> = {
  github_list_pull_requests: {
    spec: {
      type: "function",
      function: {
        name: "github_list_pull_requests",
        description: "List pull requests for a repository. Owner/repo optional if GITHUB_BRIEF_REPOS is set.",
        parameters: {
          type: "object",
          properties: {
            owner: { type: "string" },
            repo: { type: "string" },
            state: { type: "string", enum: ["open", "closed", "all"], description: "Default open" },
            per_page: { type: "integer" },
          },
        },
      },
    },
    handler: async (args: {
      owner?: string;
      repo?: string;
      state?: "open" | "closed" | "all";
      per_page?: number;
    }) => {
      const octokit = getOctokit();
      const { owner, repo } = parseRepo(args.owner, args.repo);
      const res = await octokit.rest.pulls.list({
        owner,
        repo,
        state: args.state ?? "open",
        per_page: Math.min(args.per_page ?? 20, 50),
        sort: "updated",
      });
      return res.data.map((pr) => ({
        number: pr.number,
        title: pr.title,
        state: pr.state,
        draft: pr.draft,
        html_url: pr.html_url,
        user: pr.user?.login,
        head: pr.head?.ref,
        updated_at: pr.updated_at,
      }));
    },
  },

  github_get_branch_ci_status: {
    spec: {
      type: "function",
      function: {
        name: "github_get_branch_ci_status",
        description:
          "Recent GitHub Actions workflow runs for a branch; failures first. Use for CI health on main.",
        parameters: {
          type: "object",
          properties: {
            owner: { type: "string" },
            repo: { type: "string" },
            branch: { type: "string", description: "Default main" },
            per_page: { type: "integer" },
          },
        },
      },
    },
    handler: async (args: { owner?: string; repo?: string; branch?: string; per_page?: number }) => {
      const octokit = getOctokit();
      const { owner, repo } = parseRepo(args.owner, args.repo);
      const branch = args.branch ?? "main";
      const res = await octokit.rest.actions.listWorkflowRunsForRepo({
        owner,
        repo,
        branch,
        per_page: Math.min(args.per_page ?? 15, 30),
        event: "push",
      });
      const runs = res.data.workflow_runs ?? [];
      const sorted = [...runs].sort((a, b) => {
        const af = a.conclusion === "failure" ? 0 : 1;
        const bf = b.conclusion === "failure" ? 0 : 1;
        return af - bf;
      });
      return sorted.map((run) => ({
        name: run.name,
        status: run.status,
        conclusion: run.conclusion,
        html_url: run.html_url,
        created_at: run.created_at,
        head_branch: run.head_branch,
      }));
    },
  },

  github_get_repository_readme: {
    spec: {
      type: "function",
      function: {
        name: "github_get_repository_readme",
        description: "Fetch README.md body (decoded) for a repo.",
        parameters: {
          type: "object",
          properties: { owner: { type: "string" }, repo: { type: "string" } },
        },
      },
    },
    handler: async (args: { owner?: string; repo?: string }) => {
      const octokit = getOctokit();
      const { owner, repo } = parseRepo(args.owner, args.repo);
      const file = await octokit.rest.repos.getReadme({ owner, repo, mediaType: { format: "raw" } });
      const data = file.data as unknown;
      if (typeof data === "string") return { path: "README.md", content: data.slice(0, 12000) };
      return { path: "README.md", content: String(data).slice(0, 12000) };
    },
  },

  github_list_open_issues: {
    spec: {
      type: "function",
      function: {
        name: "github_list_open_issues",
        description: "List open issues (not PRs) in a repository.",
        parameters: {
          type: "object",
          properties: {
            owner: { type: "string" },
            repo: { type: "string" },
            per_page: { type: "integer" },
          },
        },
      },
    },
    handler: async (args: { owner?: string; repo?: string; per_page?: number }) => {
      const octokit = getOctokit();
      const { owner, repo } = parseRepo(args.owner, args.repo);
      const res = await octokit.rest.issues.listForRepo({
        owner,
        repo,
        state: "open",
        per_page: Math.min(args.per_page ?? 15, 30),
      });
      return res.data
        .filter((i) => !i.pull_request)
        .map((i) => ({
          number: i.number,
          title: i.title,
          html_url: i.html_url,
          user: i.user?.login,
          labels: i.labels.map((l) => (typeof l === "string" ? l : l.name)),
        }));
    },
  },

  github_get_path_contents: {
    spec: {
      type: "function",
      function: {
        name: "github_get_path_contents",
        description: "Get file contents at a path in a repo (decoded UTF-8 for files).",
        parameters: {
          type: "object",
          properties: {
            owner: { type: "string" },
            repo: { type: "string" },
            path: { type: "string", description: "e.g. src/index.ts or docs/SETUP.md" },
            ref: { type: "string", description: "branch or SHA" },
          },
          required: ["path"],
        },
      },
    },
    handler: async (args: { owner?: string; repo?: string; path: string; ref?: string }) => {
      const octokit = getOctokit();
      const { owner, repo } = parseRepo(args.owner, args.repo);
      const file = await octokit.rest.repos.getContent({
        owner,
        repo,
        path: args.path,
        ref: args.ref,
      });
      if (Array.isArray(file.data)) {
        return {
          path: args.path,
          type: "dir",
          entries: file.data.map((e) => ({ name: e.name, type: e.type, sha: e.sha })),
        };
      }
      if (file.data.type !== "file" || !("content" in file.data)) {
        return { error: "Not a file" };
      }
      const buf = Buffer.from(file.data.content, "base64");
      return {
        path: file.data.path,
        sha: file.data.sha,
        content: buf.toString("utf8").slice(0, 12000),
        truncated: buf.length > 12000,
      };
    },
  },
};
