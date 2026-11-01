
import os
import json
import logging
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# Load .env from the same directory as this file.
load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["GitHub"])


class GitHubPRRequest(BaseModel):
    owner: str
    repo: str
    pull_number: int = Field(gt=0)


def parse_result(result):
    """Convert MCP content blocks to text values."""
    if result.is_error:
        details = [
            getattr(item, "text", str(item))
            for item in result.content
        ]
        raise RuntimeError(
            "GitHub MCP tool failed: " + " ".join(details)
        )

    return [
        item.text if hasattr(item, "text") else str(item)
        for item in result.content
    ]


def decode_result(result):
    """Decode JSON returned inside MCP text content."""
    if isinstance(result, dict):
        return result

    if not isinstance(result, list):
        return result

    if len(result) == 1 and isinstance(result[0], str):
        try:
            return json.loads(result[0])
        except json.JSONDecodeError:
            return result

    decoded = []
    for item in result:
        if isinstance(item, str):
            try:
                decoded.append(json.loads(item))
            except json.JSONDecodeError:
                decoded.append(item)
        else:
            decoded.append(item)

    return decoded


def find_list(data, *keys):
    """Find a list directly or inside a nested response object."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        for value in data.values():
            found = find_list(value, *keys)
            if found:
                return found

    return []


def module_from_path(filename):
    parts = PurePosixPath(filename).parts

    for root in (
        "src", "app", "services", "modules", "packages"
    ):
        if root in parts:
            index = parts.index(root)
            if index + 1 < len(parts):
                return f"{root}/{parts[index + 1]}"

    return parts[0] if len(parts) > 1 else None


async def fetch_github_data(owner, repo, pull_number):
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()

    if not token:
        raise RuntimeError(
            "GitHub token is not configured in the ml/.env file"
        )

    env = {
        **os.environ,
        "GITHUB_PERSONAL_ACCESS_TOKEN": token,
        "GITHUB_TOOLSETS": "repos,issues,pull_requests,actions",
        "GITHUB_READ_ONLY": "true",
    }

    params = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
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

            tool_list = (await session.list_tools()).tools
            tool_map = {tool.name: tool for tool in tool_list}

            logger.info(
                "GitHub MCP connected; available tools: %s",
                sorted(tool_map.keys()),
            )

            # async def call(name, arguments):
            #     tool = tool_map.get(name)

            #     if tool is None:
            #         raise RuntimeError(
            #             f"GitHub MCP tool unavailable: {name}"
            #         )

            #     # Use only arguments declared by this server.
            #     schema = tool.input_schema or {}
            #     properties = schema.get("properties", {})

            #     if properties:
            #         filtered = {
            #             key: value
            #             for key, value in arguments.items()
            #             if key in properties
            #         }
            #     else:
            #         filtered = arguments

            #     logger.info(
            #         "Calling GitHub MCP tool %s with arguments %s",
            #         name,
            #         sorted(filtered.keys()),
            #     )

            #     result = await session.call_tool(name, filtered)
            #     return decode_result(parse_result(result))

            async def call(name, arguments):
                tool = tool_map.get(name)

                if tool is None:
                    raise RuntimeError(
                        f"GitHub MCP tool unavailable: {name}"
                    )

                schema = tool.input_schema or {}
                properties = schema.get("properties", {})

                if properties:
                    filtered = {
                        key: value
                        for key, value in arguments.items()
                        if key in properties
                    }
                else:
                    filtered = arguments

                logger.info(
                    "Calling GitHub MCP tool %s with arguments %s",
                    name,
                    sorted(filtered.keys()),
                )

                result = await session.call_tool(name, filtered)
                return decode_result(parse_result(result))

            # 1. Retrieve pull request details.
            pr_result = await call(
                "pull_request_read",
                {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": pull_number,
                    "method": "get",
                },
            )

            if not isinstance(pr_result, dict):
                raise RuntimeError(
                    "Unexpected PR response: "
                    f"{type(pr_result).__name__}"
                )

            # Use one consistent variable name throughout.
            pr = pr_result

            logger.info(
                "Retrieved PR #%s: %s",
                pull_number,
                pr.get("title", "(untitled)"),
            )

            # 2. Retrieve changed files.
            files_result = await call(
                "pull_request_read",
                {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": pull_number,
                    "method": "get_files",
                    "perPage": 100,
                },
            )

            files = find_list(files_result, "files")

            modules = {
                module_from_path(item["filename"])
                for item in files
                if isinstance(item, dict)
                and item.get("filename")
            }
            modules.discard(None)

            # 3. Retrieve open bug issues.
            # Do not send page: this server uses cursor pagination.
            issues_result = await call(
                "list_issues",
                {
                    "owner": owner,
                    "repo": repo,
                    "state": "open",
                    "labels": ["bug"],
                    "perPage": 100,
                },
            )

            issues = find_list(
                issues_result,
                "issues",
                "nodes",
            )

            defects = [
                issue
                for issue in issues
                if isinstance(issue, dict)
                and str(issue.get("state", "open")).lower() == "open"
                and "pull_request" not in issue
            ]

            # 4. Retrieve recent GitHub Actions workflow runs.
            base = pr.get("base") or {}
            base_branch = (
                base.get("ref")
                if isinstance(base, dict)
                else None
            )

            workflow_filter = {
                "status": "completed",
            }

            if base_branch:
                workflow_filter["branch"] = base_branch

            actions_result = await call(
                "actions_list",
                {
                    "method": "list_workflow_runs",
                    "owner": owner,
                    "repo": repo,
                    "perPage": 100,
                    "workflow_runs_filter": workflow_filter,
                },
            )

            runs = find_list(
                actions_result,
                "workflow_runs",
                "workflowRuns",
                "runs",
            )

            failures = sum(
                1
                for run in runs
                if isinstance(run, dict)
                and str(run.get("conclusion", "")).lower()
                == "failure"
            )

            # 5. Determine criticality from PR labels if available.
            labels = pr.get("labels") or []

            label_names = {
                (
                    label.get("name", "")
                    if isinstance(label, dict)
                    else str(label)
                ).lower()
                for label in labels
            }

            criticality = next(
                (
                    level
                    for level in ("high", "medium", "low")
                    if (
                        f"criticality:{level}" in label_names
                        or f"priority:{level}" in label_names
                    )
                ),
                "medium",
            )

            # 6. Assemble relevant descriptions.
            descriptions = []

            if pr.get("title"):
                descriptions.append(
                    f"Pull request: {pr['title']}"
                )

            if pr.get("body"):
                descriptions.append(pr["body"])

            for issue in defects:
                if issue.get("body"):
                    descriptions.append(
                        f"Issue #{issue.get('number')}: "
                        f"{issue['body']}"
                    )

            changed_lines = (
                int(pr.get("additions", 0))
                + int(pr.get("deletions", 0))
            )

            return {
                "changed_files": int(
                    pr.get("changed_files", len(files))
                ),
                "changed_lines": changed_lines,
                "affected_modules": len(modules),
                "open_defects": len(defects),
                "criticality": criticality,
                "recent_failures": failures,
                "defect_description": "\n\n".join(
                    descriptions
                ) or (
                    "No PR or defect description found; "
                    "manual review needed."
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
        # Keep the full traceback in server logs, not the API response.
        logger.exception("GitHub MCP request failed")

        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to retrieve GitHub data: "
                f"{type(exc).__name__}: {str(exc)}"
            ),
        ) from exc
