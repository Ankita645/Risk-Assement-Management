
import os
import json
import asyncio
from pathlib import PurePosixPath

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv("ml/.env")

router = APIRouter(prefix="/github", tags=["GitHub"])

class GitHubPRRequest(BaseModel):
    owner: str
    repo: str
    pull_number: int = Field(gt=0)



def parse_result(result):
    if result.is_error:
        details = [
            getattr(item, "text", str(item))
            for item in result.content
        ]
        raise RuntimeError(
            "GitHub MCP tool failed: " + " ".join(details)
        )

    parsed = []

    for item in result.content:
        if hasattr(item, "text"):
            parsed.append(item.text)
        else:
            parsed.append(str(item))

    return parsed


def find_list(data, *keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
        for value in data.values():
            found = find_list(value, *keys)
            if found:
                return found
    return []


def module_from_path(filename):
    parts = PurePosixPath(filename).parts
    for root in ("src", "app", "services", "modules", "packages"):
        if root in parts:
            index = parts.index(root)
            if index + 1 < len(parts):
                return f"{root}/{parts[index + 1]}"
    return parts[0] if len(parts) > 1 else None


async def fetch_github_data(owner, repo, pull_number):
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GitHub token is not configured")
    print("token",token)
    env = {
        **os.environ,
        "GITHUB_PERSONAL_ACCESS_TOKEN": token,
        "GITHUB_TOOLSETS": "repos,issues,pull_requests,actions",
        "GITHUB_READ_ONLY": "true",
    }

    params = StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e", "GITHUB_TOOLSETS",
            "-e", "GITHUB_READ_ONLY",
            "ghcr.io/github/github-mcp-server",
        ],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {
                tool.name for tool in (await session.list_tools()).tools
            }

            async def call(name, arguments):
                if name not in tools:
                    raise RuntimeError(f"MCP tool unavailable: {name}")
                result = await session.call_tool(name, arguments)
                return parse_result(result)

            pr_result = await call("pull_request_read", {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get",
            })

            pr = pr_result
            if isinstance(pr_result, dict):
                pr = pr_result.get("pull_request", pr_result)

            if not isinstance(pr, dict):
                raise RuntimeError("Unexpected pull request response")

            files_result = await call("pull_request_read", {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get_files",
                "page": 1,
                "perPage": 100,
            })

            files = find_list(files_result, "files")
            modules = {
                module_from_path(f["filename"])
                for f in files
                if isinstance(f, dict) and f.get("filename")
            }
            modules.discard(None)

            issues_result = await call("list_issues", {
                "owner": owner,
                "repo": repo,
                "state": "open",
                "labels": ["bug"],
                "perPage": 100,
                "page": 1,
            })

            issues = find_list(issues_result, "issues")
            defects = [
                i for i in issues
                if isinstance(i, dict)
                and i.get("state", "open") == "open"
                and "pull_request" not in i
            ]

            base = pr.get("base") or {}
            base_branch = (
                base.get("ref") if isinstance(base, dict) else None
            )

            actions_result = await call("actions_list", {
                "method": "list_workflow_runs",
                "owner": owner,
                "repo": repo,
                "perPage": 100,
                "page": 1,
                "workflow_runs_filter": {
                    "status": "completed",
                    **({"branch": base_branch} if base_branch else {}),
                },
            })

            runs = find_list(actions_result, "workflow_runs", "runs")
            failures = sum(
                1 for run in runs
                if isinstance(run, dict)
                and run.get("conclusion") == "failure"
            )

            labels = pr.get("labels") or []
            label_names = {
                (
                    label.get("name", "") if isinstance(label, dict)
                    else str(label)
                ).lower()
                for label in labels
            }

            criticality = next(
                (
                    level for level in ("high", "medium", "low")
                    if f"criticality:{level}" in label_names
                    or f"priority:{level}" in label_names
                ),
                "medium",
            )

            descriptions = []
            if pr.get("body"):
                descriptions.append(pr["body"])

            for issue in defects:
                if issue.get("body"):
                    descriptions.append(
                        f"Issue #{issue.get('number')}: {issue['body']}"
                    )

            return {
                "changed_files": int(
                    pr.get("changed_files", len(files))
                ),
                "changed_lines": (
                    int(pr.get("additions", 0))
                    + int(pr.get("deletions", 0))
                ),
                "affected_modules": len(modules),
                "open_defects": len(defects),
                "criticality": criticality,
                "recent_failures": failures,
                "defect_description": "\n\n".join(descriptions) or (
                    "No PR or defect description found; manual review needed."
                ),
            }


@router.post("/release-data")
async def get_release_data(payload: GitHubPRRequest):
    try:
        return await fetch_github_data(
            payload.owner,
            payload.repo,
            payload.pull_number,
        )
    except Exception as exc:
        # Log full details server-side, never expose credentials.
        import logging
        logging.exception("GitHub MCP request failed")
        raise HTTPException(
            status_code=502,
            detail=f"Unable to retrieve GitHub data: {type(exc).__name__}",
        ) from exc
