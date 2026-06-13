# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""carter-ops: jira-create — create a Jira ticket."""
from __future__ import annotations

from typing import Any

from carter.ops.attribution import append_jira_footer, attribution_summary
from carter.ops.config import Config
from carter.ops.operations import Operation, Plan, Result, register
from carter.ops.operations.jira_comment import _jira_headers


@register
class JiraCreate(Operation):
    name = "jira-create"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("project"):
            errors.append("--project is required")
        if not params.get("type"):
            errors.append("--type is required")
        if not params.get("summary"):
            errors.append("--summary is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        project = params["project"]
        issue_type = params["type"]
        summary = params["summary"]
        priority = params.get("priority", "Medium")
        labels = params.get("labels", [])
        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",")]

        steps = [
            "POST /rest/api/3/issue",
            f"Project: {project}",
            f"Type: {issue_type}",
            f"Summary: {summary}",
            f"Priority: {priority}",
        ]
        if labels:
            steps.append(f"Labels: {', '.join(labels)}")

        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "jira"),
            side_effects=[f"New {issue_type} in {project}"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        import httpx

        project = params["project"]
        issue_type = params["type"]
        summary = params["summary"]
        description = params.get("description", "")
        priority = params.get("priority", "Medium")
        labels = params.get("labels", [])
        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",")]

        # Append footer to description if present
        if description:
            description = append_jira_footer(description, cfg)

        url = f"{cfg.jira_url.rstrip('/')}/rest/api/3/issue"

        # Build ADF description
        desc_content = []
        if description:
            desc_content = [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ]

        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": project},
                "issuetype": {"name": issue_type},
                "summary": summary,
                "priority": {"name": priority},
            }
        }

        if desc_content:
            payload["fields"]["description"] = {
                "type": "doc",
                "version": 1,
                "content": desc_content,
            }

        if labels:
            payload["fields"]["labels"] = labels

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=_jira_headers(cfg),
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
                attribution=attribution_summary(cfg, "jira"),
            )
        except httpx.RequestError as e:
            return Result(
                operation=self.name,
                success=False,
                data={"error": "REQUEST_FAILED", "message": str(e)},
                attribution=attribution_summary(cfg, "jira"),
            )

        return Result(
            operation=self.name,
            success=True,
            data={
                "key": data.get("key", ""),
                "id": data.get("id", ""),
                "url": f"{cfg.jira_url.rstrip('/')}/browse/{data.get('key', '')}",
            },
            attribution=attribution_summary(cfg, "jira"),
        )
