from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from src.config import get_settings
from src.connections.repository import resolve_extra
from src.exceptions import ConfigError
from src.integrations.github import github_client

ACTIVE_REPO_DAYS = 14
BRIEF_REPO_LIMIT = 10
_AFFILIATIONS = frozenset({"owner", "collaborator", "organization_member"})
_REPO_SORTS = frozenset({"created", "updated", "pushed", "full_name"})
_SEARCH_SORTS = frozenset({"comments", "reactions", "created", "updated"})


def parse_repo(
    owner: str | None,
    repo: str | None,
    *,
    username: str | None = None,
) -> tuple[str, str]:
    settings = get_settings()
    o = (owner or "").strip()
    r = (repo or "").strip()
    if o and r:
        return o, r
    login = (username or settings.GITHUB_USERNAME or "").strip()
    if login and r:
        return login, r
    raise ConfigError("Provide owner and repo")


async def resolve_repo(owner: str | None, repo: str | None) -> tuple[str, str]:
    extra = await resolve_extra("github")
    return parse_repo(owner, repo, username=str(extra.get("username") or "") or None)


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def repo_is_usable(repo: dict[str, Any]) -> bool:
    full = (repo.get("full_name") or "").strip()
    if "/" not in full or repo.get("archived") or repo.get("disabled"):
        return False
    return True


def _pushed_sort_key(repo: dict[str, Any]) -> datetime:
    return parse_github_datetime(repo.get("pushed_at")) or datetime.min.replace(tzinfo=UTC)


def select_active_repos(
    repos: list[dict[str, Any]],
    *,
    now: datetime,
    days: int,
    limit: int,
) -> list[dict[str, Any]]:
    usable = [repo for repo in repos if repo_is_usable(repo)]
    cutoff = now - timedelta(days=days)
    recent = [
        repo
        for repo in usable
        if (pushed := parse_github_datetime(repo.get("pushed_at"))) is not None and pushed >= cutoff
    ]
    chosen = recent or usable
    chosen.sort(key=_pushed_sort_key, reverse=True)
    return chosen[:limit]


def compact_repo(repo: dict[str, Any]) -> dict[str, Any]:
    full = (repo.get("full_name") or "").strip()
    owner, _, name = full.partition("/")
    description = (repo.get("description") or "").strip()
    return {
        "full_name": full,
        "owner": owner,
        "name": name,
        "private": repo.get("private"),
        "fork": repo.get("fork"),
        "pushed_at": repo.get("pushed_at"),
        "default_branch": repo.get("default_branch") or "main",
        "language": repo.get("language"),
        "open_issues_count": repo.get("open_issues_count"),
        "html_url": repo.get("html_url"),
        "description": description[:200] or None,
    }


def repo_from_repository_url(url: str | None) -> str | None:
    if not url:
        return None
    marker = "/repos/"
    idx = url.find(marker)
    if idx == -1:
        return None
    return url[idx + len(marker) :].strip("/") or None


def compact_issue(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo": repo_from_repository_url(item.get("repository_url")),
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "html_url": item.get("html_url"),
        "user": (item.get("user") or {}).get("login"),
        "is_pull_request": bool(item.get("pull_request")),
        "updated_at": item.get("updated_at"),
        "labels": [
            label if isinstance(label, str) else label.get("name")
            for label in item.get("labels") or []
        ],
    }


def _affiliation_param(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text or text == "all":
        return "owner,collaborator,organization_member"
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts or any(part not in _AFFILIATIONS for part in parts):
        return "owner,collaborator,organization_member"
    return ",".join(parts)


def _per_page(args: dict[str, Any], default: int, max_n: int) -> int:
    raw = args.get("per_page") or default
    try:
        return min(max(int(raw), 1), max_n)
    except (TypeError, ValueError):
        return default


async def fetch_active_repos(
    client: httpx.AsyncClient,
    *,
    days: int = ACTIVE_REPO_DAYS,
    limit: int = BRIEF_REPO_LIMIT,
) -> list[dict[str, Any]]:
    res = await client.get(
        "/user/repos",
        params={
            "sort": "pushed",
            "direction": "desc",
            "per_page": min(max(limit * 3, 20), 50),
            "affiliation": "owner,collaborator,organization_member",
        },
    )
    res.raise_for_status()
    selected = select_active_repos(
        res.json(),
        now=datetime.now(UTC),
        days=days,
        limit=limit,
    )
    return [compact_repo(repo) for repo in selected]


async def _list_repos(args: dict[str, Any]) -> list[dict[str, Any]]:
    per_page = _per_page(args, 20, 50)
    sort = args.get("sort") if args.get("sort") in _REPO_SORTS else "pushed"
    params: dict[str, Any] = {
        "sort": sort,
        "direction": "desc",
        "per_page": per_page,
        "affiliation": _affiliation_param(args.get("affiliation")),
    }
    visibility = args.get("visibility")
    if visibility in {"all", "public", "private"}:
        params["visibility"] = visibility
    async with github_client() as client:
        res = await client.get("/user/repos", params=params)
        res.raise_for_status()
        repos = [repo for repo in res.json() if repo_is_usable(repo)]
        days = args.get("active_days")
        if days is not None:
            try:
                active_days = max(int(days), 1)
            except (TypeError, ValueError):
                active_days = ACTIVE_REPO_DAYS
            repos = select_active_repos(
                repos,
                now=datetime.now(UTC),
                days=active_days,
                limit=per_page,
            )
        return [compact_repo(repo) for repo in repos]


async def _search_issues(args: dict[str, Any]) -> dict[str, Any]:
    q = (args.get("q") or "").strip() or "involves:@me is:open"
    params: dict[str, Any] = {"q": q, "per_page": _per_page(args, 20, 30)}
    sort = args.get("sort")
    if sort in _SEARCH_SORTS:
        params["sort"] = sort
        params["order"] = args.get("order") if args.get("order") in {"asc", "desc"} else "desc"
    async with github_client() as client:
        res = await client.get("/search/issues", params=params)
        res.raise_for_status()
        payload = res.json()
        return {
            "total_count": payload.get("total_count"),
            "incomplete_results": payload.get("incomplete_results"),
            "query": q,
            "items": [compact_issue(item) for item in payload.get("items") or []],
        }


async def _list_prs(args: dict[str, Any]) -> list[dict[str, Any]]:
    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": args.get("state") or "open",
                "per_page": _per_page(args, 20, 50),
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
    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
    branch = args.get("branch") or "main"
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/actions/runs",
            params={
                "branch": branch,
                "per_page": _per_page(args, 15, 30),
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
    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw"},
        )
        res.raise_for_status()
        return {"path": "README.md", "content": res.text[:12000]}


async def _open_issues(args: dict[str, Any]) -> list[dict[str, Any]]:
    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
    async with github_client() as client:
        res = await client.get(
            f"/repos/{owner}/{repo}/issues",
            params={"state": "open", "per_page": _per_page(args, 15, 30)},
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

    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
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


def issue_create_body(args: dict[str, Any]) -> dict[str, Any]:
    title = (args.get("title") or "").strip()
    if not title:
        raise ConfigError("title is required")
    body: dict[str, Any] = {"title": title}
    if args.get("body"):
        body["body"] = str(args["body"])
    labels = args.get("labels")
    if isinstance(labels, list):
        body["labels"] = [str(label) for label in labels if str(label).strip()]
    elif isinstance(labels, str) and labels.strip():
        body["labels"] = [part.strip() for part in labels.split(",") if part.strip()]
    return body


def comment_create_body(args: dict[str, Any]) -> dict[str, Any]:
    text = (args.get("body") or "").strip()
    if not text:
        raise ConfigError("body is required")
    return {"body": text}


def pull_merge_body(args: dict[str, Any]) -> dict[str, Any]:
    method = (args.get("merge_method") or "squash").strip()
    if method not in {"merge", "squash", "rebase"}:
        method = "squash"
    body: dict[str, Any] = {"merge_method": method}
    if args.get("commit_title"):
        body["commit_title"] = str(args["commit_title"])
    if args.get("commit_message"):
        body["commit_message"] = str(args["commit_message"])
    return body


def _issue_number(args: dict[str, Any]) -> int:
    try:
        return int(args.get("number"))
    except (TypeError, ValueError) as err:
        raise ConfigError("number is required") from err


async def _create_issue(args: dict[str, Any]) -> dict[str, Any]:
    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
    async with github_client() as client:
        res = await client.post(f"/repos/{owner}/{repo}/issues", json=issue_create_body(args))
        res.raise_for_status()
        issue = res.json()
        return {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "html_url": issue.get("html_url"),
            "state": issue.get("state"),
        }


async def _add_comment(args: dict[str, Any]) -> dict[str, Any]:
    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
    number = _issue_number(args)
    async with github_client() as client:
        res = await client.post(
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json=comment_create_body(args),
        )
        res.raise_for_status()
        comment = res.json()
        return {
            "id": comment.get("id"),
            "html_url": comment.get("html_url"),
            "number": number,
        }


async def _merge_pr(args: dict[str, Any]) -> dict[str, Any]:
    owner, repo = await resolve_repo(args.get("owner"), args.get("repo"))
    number = _issue_number(args)
    async with github_client() as client:
        res = await client.put(
            f"/repos/{owner}/{repo}/pulls/{number}/merge",
            json=pull_merge_body(args),
        )
        res.raise_for_status()
        payload = res.json()
        return {
            "merged": payload.get("merged"),
            "sha": payload.get("sha"),
            "message": payload.get("message"),
            "number": number,
        }


github_tools = {
    "github_list_repos": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_list_repos",
                "description": (
                    "List repositories the GitHub token can access (personal + orgs). "
                    "Sorted by last push by default. Set active_days to keep only recently pushed repos. "
                    "Use this to discover owner/repo, then call per-repo tools."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "affiliation": {
                            "type": "string",
                            "description": (
                                "owner, collaborator, organization_member, comma-separated, or all. "
                                "Default all."
                            ),
                        },
                        "visibility": {
                            "type": "string",
                            "enum": ["all", "public", "private"],
                        },
                        "sort": {
                            "type": "string",
                            "enum": ["created", "updated", "pushed", "full_name"],
                            "description": "Default pushed",
                        },
                        "active_days": {
                            "type": "integer",
                            "description": (
                                "If set, only repos pushed within this many days "
                                "(falls back to most recently pushed if none match)."
                            ),
                        },
                        "per_page": {"type": "integer"},
                    },
                },
            },
        },
        "handler": _list_repos,
    },
    "github_search_issues": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_search_issues",
                "description": (
                    "Search issues and pull requests across all repos the token can see. "
                    "GitHub search syntax, e.g. is:pr is:open involves:@me, is:issue org:acme. "
                    "Default query: involves:@me is:open."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "q": {
                            "type": "string",
                            "description": "GitHub issues search query. Default involves:@me is:open",
                        },
                        "sort": {
                            "type": "string",
                            "enum": ["comments", "reactions", "created", "updated"],
                        },
                        "order": {"type": "string", "enum": ["asc", "desc"]},
                        "per_page": {"type": "integer"},
                    },
                },
            },
        },
        "handler": _search_issues,
    },
    "github_list_pull_requests": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_list_pull_requests",
                "description": (
                    "List pull requests for a repository. "
                    "Owner optional after connect github if repo is provided."
                ),
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
    "github_create_issue": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_create_issue",
                "description": "Create an issue in a repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "labels": {
                            "type": "string",
                            "description": "Comma-separated label names",
                        },
                    },
                    "required": ["title"],
                },
            },
        },
        "handler": _create_issue,
    },
    "github_add_comment": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_add_comment",
                "description": "Comment on an issue or pull request by number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "number": {"type": "integer"},
                        "body": {"type": "string"},
                    },
                    "required": ["number", "body"],
                },
            },
        },
        "handler": _add_comment,
    },
    "github_merge_pull_request": {
        "spec": {
            "type": "function",
            "function": {
                "name": "github_merge_pull_request",
                "description": (
                    "Merge a pull request. Only call after the user explicitly confirmed the merge."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "number": {"type": "integer"},
                        "merge_method": {
                            "type": "string",
                            "enum": ["merge", "squash", "rebase"],
                            "description": "Default squash",
                        },
                        "commit_title": {"type": "string"},
                        "commit_message": {"type": "string"},
                    },
                    "required": ["number"],
                },
            },
        },
        "handler": _merge_pr,
    },
}
