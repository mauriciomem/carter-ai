# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""carter-ops: gh-pr — create a GitHub pull request."""
from __future__ import annotations

from typing import Any

from attribution import append_github_footer, attribution_summary
from config import Config
from operations import Operation, Plan, Result, register
from operations.gh_issue import _GITHUB_API, _github_headers


@register
class GhPr(Operation):
    name = "gh-pr"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("repo"):
            errors.append("--repo is required (owner/repo)")
        elif "/" not in params["repo"]:
            errors.append("--repo must be in owner/repo format")
        if not params.get("title"):
            errors.append("--title is required")
        if not params.get("head"):
            errors.append("--head is required (source branch)")
        if not params.get("base"):
            errors.append("--base is required (target branch)")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        repo = params["repo"]
        title = params["title"]
        head = params["head"]
        base = params["base"]
        body = params.get("body", "")
        draft = params.get("draft", False)

        steps = [
            f"POST /repos/{repo}/pulls",
            f"Title: {title}",
            f"Head: {head} → Base: {base}",
        ]
        if body:
            steps.append(f"Body: {body[:200]}{'...' if len(body) > 200 else ''}")
        if draft:
            steps.append("Draft: yes")

        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "github"),
            side_effects=[f"New PR in {repo}: {head} → {base}"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        import httpx

        repo = params["repo"]
        title = params["title"]
        head = params["head"]
        base = params["base"]
        body = params.get("body", "")
        draft = params.get("draft", False)

        body_with_footer = append_github_footer(body, cfg) if body else ""

        payload: dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
        }
        if body_with_footer:
            payload["body"] = body_with_footer
        if draft:
            payload["draft"] = True

        url = f"{_GITHUB_API}/repos/{repo}/pulls"

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
                "number": data.get("number", ""),
                "url": data.get("html_url", ""),
                "title": data.get("title", ""),
                "draft": data.get("draft", False),
            },
            attribution=attribution_summary(cfg, "github"),
        )
