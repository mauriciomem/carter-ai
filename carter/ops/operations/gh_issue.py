# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""carter-ops: gh-issue — create a GitHub issue."""

from __future__ import annotations

from typing import Any

from carter.ops.attribution import append_github_footer, attribution_summary
from carter.ops.config import Config
from carter.ops.operations import Operation, Plan, Result, register

_GITHUB_API = "https://api.github.com"


def _github_headers(cfg: Config) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@register
class GhIssue(Operation):
    name = "gh-issue"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("repo"):
            errors.append("--repo is required (owner/repo)")
        elif "/" not in params["repo"]:
            errors.append("--repo must be in owner/repo format")
        if not params.get("title"):
            errors.append("--title is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        repo = params["repo"]
        title = params["title"]
        body = params.get("body", "")
        labels = params.get("labels", [])
        if isinstance(labels, str):
            labels = [label.strip() for label in labels.split(",")]

        steps = [
            f"POST /repos/{repo}/issues",
            f"Title: {title}",
        ]
        if body:
            steps.append(f"Body: {body[:200]}{'...' if len(body) > 200 else ''}")
        if labels:
            steps.append(f"Labels: {', '.join(labels)}")

        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "github"),
            side_effects=[f"New issue in {repo}"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        import httpx

        repo = params["repo"]
        title = params["title"]
        body = params.get("body", "")
        labels = params.get("labels", [])
        if isinstance(labels, str):
            labels = [label.strip() for label in labels.split(",")]

        body_with_footer = append_github_footer(body, cfg) if body else ""

        payload: dict[str, Any] = {"title": title}
        if body_with_footer:
            payload["body"] = body_with_footer
        if labels:
            payload["labels"] = labels

        url = f"{_GITHUB_API}/repos/{repo}/issues"

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
            },
            attribution=attribution_summary(cfg, "github"),
        )
