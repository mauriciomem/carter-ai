# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""carter-ops: gh-pr-comment — comment on a GitHub pull request."""
from __future__ import annotations

from typing import Any

from carter.ops.attribution import append_github_footer, attribution_summary
from carter.ops.config import Config
from carter.ops.operations import Operation, Plan, Result, register
from carter.ops.operations.gh_issue import _GITHUB_API, _github_headers


@register
class GhPrComment(Operation):
    name = "gh-pr-comment"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("repo"):
            errors.append("--repo is required (owner/repo)")
        elif "/" not in params["repo"]:
            errors.append("--repo must be in owner/repo format")
        if not params.get("pr"):
            errors.append("--pr is required (PR number)")
        if not params.get("body"):
            errors.append("--body is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        repo = params["repo"]
        pr = params["pr"]
        body = params["body"]
        body_with_footer = append_github_footer(body, cfg)

        steps = [
            f"POST /repos/{repo}/issues/{pr}/comments",
            f"Body: {body_with_footer[:200]}{'...' if len(body_with_footer) > 200 else ''}",
        ]
        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "github"),
            side_effects=[f"New comment on {repo}#{pr}"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        import httpx

        repo = params["repo"]
        pr = params["pr"]
        body = params["body"]
        body_with_footer = append_github_footer(body, cfg)

        # GitHub uses the issues API for PR comments (general comments)
        url = f"{_GITHUB_API}/repos/{repo}/issues/{pr}/comments"
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
