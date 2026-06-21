# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""carter-ops: jira-comment — add a comment to a Jira ticket."""

from __future__ import annotations

import re
from typing import Any

from carter.ops.attribution import append_jira_footer, attribution_summary
from carter.ops.config import Config
from carter.ops.operations import Operation, Plan, Result, register


def _jira_headers(cfg: Config) -> dict[str, str]:
    import base64

    creds = base64.b64encode(f"{cfg.jira_email}:{cfg.jira_token}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@register
class JiraComment(Operation):
    name = "jira-comment"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("ticket"):
            errors.append("--ticket is required")
        elif not re.match(r"^[A-Z][A-Z0-9]+-\d+$", params["ticket"]):
            errors.append(f"Invalid ticket key format: {params['ticket']}")
        if not params.get("body"):
            errors.append("--body is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        ticket = params["ticket"]
        body = params["body"]
        body_with_footer = append_jira_footer(body, cfg)
        steps = [
            f"POST /rest/api/3/issue/{ticket}/comment",
            f"Body: {body_with_footer[:200]}{'...' if len(body_with_footer) > 200 else ''}",
        ]
        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "jira"),
            side_effects=[f"New comment on {ticket}"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        import httpx

        ticket = params["ticket"]
        body = params["body"]
        body_with_footer = append_jira_footer(body, cfg)

        url = f"{cfg.jira_url.rstrip('/')}/rest/api/3/issue/{ticket}/comment"
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": body_with_footer},
                        ],
                    }
                ],
            }
        }

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
                "ticket": ticket,
                "comment_id": data.get("id", ""),
                "comment_url": data.get("self", ""),
            },
            attribution=attribution_summary(cfg, "jira"),
        )
