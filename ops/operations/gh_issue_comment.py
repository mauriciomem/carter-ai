# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""carter-ops: gh-issue-comment — comment on a GitHub issue."""
from __future__ import annotations

from typing import Any

from attribution import append_github_footer, attribution_summary
from config import Config
from operations import Operation, Plan, Result, register
from operations.gh_issue import _GITHUB_API, _github_headers


@register
class GhIssueComment(Operation):
    name = "gh-issue-comment"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("repo"):
            errors.append("--repo is required (owner/repo)")
        elif "/" not in params["repo"]:
            errors.append("--repo must be in owner/repo format")
        if not params.get("issue"):
            errors.append("--issue is required (issue number)")
        if not params.get("body"):
            errors.append("--body is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        repo = params["repo"]
        issue = params["issue"]
        body = params["body"]
        body_with_footer = append_github_footer(body, cfg)

        steps = [
            f"POST /repos/{repo}/issues/{issue}/comments",
            f"Body: {body_with_footer[:200]}{'...' if len(body_with_footer) > 200 else ''}",
        ]
        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "github"),
            side_effects=[f"New comment on {repo}#{issue}"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        import httpx

        repo = params["repo"]
        issue = params["issue"]
        body = params["body"]
        body_with_footer = append_github_footer(body, cfg)

        url = f"{_GITHUB_API}/repos/{repo}/issues/{issue}/comments"
        payload = {"body": body_with_footer}

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=_github_headers(cfg),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            return Result(
                operation=self.name,
                success=False,
                data={
                    "error": f"HTTP {e.response.status_code}",
                    "message": e.response.text[:500],
                },
                attribution=attribution_summary(cfg, "github"),
            )
        except httpx.RequestError as e:
            return Result(
                operation=self.name,
                success=False,
                data={"error": "REQUEST_FAILED", "message": str(e)},
                attribution=attribution_summary(cfg, "github"),
            )

        return Result(
            operation=self.name,
            success=True,
            data={
                "comment_id": data.get("id", ""),
                "url": data.get("html_url", ""),
            },
            attribution=attribution_summary(cfg, "github"),
        )
