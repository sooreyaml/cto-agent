from typing import Any

from src.config import get_settings
from src.exceptions import ConfigError
from src.integrations.github import github_client


def parse_repo(owner: str | None, repo: str | None) -> tuple[str, str]:
    settings = get_settings()
    o = (owner or "").strip()
    r = (repo or "").strip()
    if o and r:
        return o, r
    first = (
        settings.GITHUB_BRIEF_REPOS.split(",")[0] if settings.GITHUB_BRIEF_REPOS else ""
    ).strip()
    if "/" in first:
        left, right = first.split("/", 1)
        if left and right:
            return left, right
    if settings.GITHUB_USERNAME and r:
        return settings.GITHUB_USERNAME, r
    raise ConfigError("Provide owner and repo, or set GITHUB_BRIEF_REPOS=owner/repo")


async def _list_prs(args: dict[str, Any]) -> list[dict[str, Any]]:
    owner, repo = parse_repo(args.get("owner"), args.get("repo"))
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": args.get("state") or "open",
                "per_page": min(args.get("per_page") or 20, 50),
                "sort": "updated",
            },
        )
        res.raise_for_status()
        return [
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "draft": pr.get("draft"),
                "html_url": pr.get("html_url"),
                "user": (pr.get("user") or {}).get("login"),
                "head": (pr.get("head") or {}).get("ref"),
                "updated_at": pr.get("updated_at"),
            }
            for pr in res.json()
        ]


async def _branch_ci(args: dict[str, Any]) -> list[dict[str, Any]]:
    owner, repo = parse_repo(args.get("owner"), args.get("repo"))
    branch = args.get("branch") or "main"
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/actions/runs",
            params={
                "branch": branch,
                "per_page": min(args.get("per_page") or 15, 30),
                "event": "push",
            },
        )
        res.raise_for_status()
        runs = res.json().get("workflow_runs") or []
        runs.sort(key=lambda run: 0 if run.get("conclusion") == "failure" else 1)
        return [
            {
                "name": run.get("name"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "html_url": run.get("html_url"),
                "created_at": run.get("created_at"),
                "head_branch": run.get("head_branch"),
            }
            for run in runs
        ]


async def _readme(args: dict[str, Any]) -> dict[str, Any]:
    owner, repo = parse_repo(args.get("owner"), args.get("repo"))
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw"},
        )
        res.raise_for_status()
        return {"path": "README.md", "content": res.text[:12000]}


async def _open_issues(args: dict[str, Any]) -> list[dict[str, Any]]:
    owner, repo = parse_repo(args.get("owner"), args.get("repo"))
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/issues",
            params={"state": "open", "per_page": min(args.get("per_page") or 15, 30)},
        )
        res.raise_for_status()
        return [
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "html_url": issue.get("html_url"),
                "user": (issue.get("user") or {}).get("login"),
                "labels": [
                    label if isinstance(label, str) else label.get("name")
                    for label in issue.get("labels") or []
                ],
            }
            for issue in res.json()
            if not issue.get("pull_request")
        ]


async def _path_contents(args: dict[str, Any]) -> dict[str, Any]:
    import base64

    owner, repo = parse_repo(args.get("owner"), args.get("repo"))
    params = {}
    if args.get("ref"):
        params["ref"] = args["ref"]
    async with github_client() as client:
        res = await client.get(f"/repos/{owner}/{repo}/contents/{args['path']}", params=params)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, list):
            return {
                "path": args["path"],
                "type": "dir",
                "entries": [
                    {"name": e.get("name"), "type": e.get("type"), "sha": e.get("sha")}
                    for e in data
                ],
            }
        if data.get("type") != "file" or "content" not in data:
            return {"error": "Not a file"}
        buf = base64.b64decode(data["content"])
        return {
            "path": data.get("path"),
            "sha": data.get("sha"),
            "content": buf.decode("utf-8", errors="replace")[:12000],
            "truncated": len(buf) > 12000,
        }


github_tools = {
    "github_list_pull_requests": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_list_pull_requests",
                "description": "List pull requests for a repository. Owner/repo optional if GITHUB_BRIEF_REPOS is set.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "description": "Default open",
                        },
                        "per_page": {"type": "integer"},
                    },
                },
            },
        },
        "handler": _list_prs,
    },
    "github_get_branch_ci_status": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_get_branch_ci_status",
                "description": "Recent GitHub Actions workflow runs for a branch; failures first. Use for CI health on main.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "branch": {"type": "string", "description": "Default main"},
                        "per_page": {"type": "integer"},
                    },
                },
            },
        },
        "handler": _branch_ci,
    },
    "github_get_repository_readme": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_get_repository_readme",
                "description": "Fetch README.md body (decoded) for a repo.",
                "parameters": {
                    "type": "object",
                    "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}},
                },
            },
        },
        "handler": _readme,
    },
    "github_list_open_issues": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_list_open_issues",
                "description": "List open issues (not PRs) in a repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "per_page": {"type": "integer"},
                    },
                },
            },
        },
        "handler": _open_issues,
    },
    "github_get_path_contents": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_get_path_contents",
                "description": "Get file contents at a path in a repo (decoded UTF-8 for files).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "path": {
                            "type": "string",
                            "description": "e.g. src/index.ts or docs/SETUP.md",
                        },
                        "ref": {"type": "string", "description": "branch or SHA"},
                    },
                    "required": ["path"],
                },
            },
        },
        "handler": _path_contents,
    },
}
