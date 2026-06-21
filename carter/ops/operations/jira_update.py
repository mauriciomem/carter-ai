# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""carter-ops: jira-update — composite: add comment + optionally transition status."""

from __future__ import annotations

from typing import Any

from carter.ops.attribution import attribution_summary
from carter.ops.config import Config
from carter.ops.operations import Operation, Plan, Result, register
from carter.ops.operations.jira_comment import JiraComment, _jira_headers


@register
class JiraUpdate(Operation):
    name = "jira-update"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("ticket"):
            errors.append("--ticket is required")
        if not params.get("comment") and not params.get("transition"):
            errors.append("--comment and/or --transition is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        ticket = params["ticket"]
        comment = params.get("comment", "")
        transition = params.get("transition", "")

        steps = []
        side_effects = []

        if comment:
            steps.append(f"POST /rest/api/3/issue/{ticket}/comment")
            side_effects.append(f"New comment on {ticket}")

        if transition:
            steps.append(f"POST /rest/api/3/issue/{ticket}/transitions")
            steps.append(f"Transition to: {transition}")
            side_effects.append(f"Status changed to '{transition}'")

        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "jira"),
            side_effects=side_effects,
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        ticket = params["ticket"]
        comment = params.get("comment", "")
        transition = params.get("transition", "")
        results: dict[str, Any] = {"ticket": ticket}

        # Step 1: Comment
        if comment:
            comment_op = JiraComment()
            comment_result = comment_op.execute(
                {"ticket": ticket, "body": comment},
                cfg,
            )
            if not comment_result.success:
                return Result(
                    operation=self.name,
                    success=False,
                    data={"failed_step": "jira-comment", **comment_result.data},
                    attribution=attribution_summary(cfg, "jira"),
                )
            results["comment_id"] = comment_result.data.get("comment_id", "")

        # Step 2: Transition
        if transition:
            transition_result = self._transition(ticket, transition, cfg)
            if not transition_result["success"]:
                return Result(
                    operation=self.name,
                    success=False,
                    data={"failed_step": "transition", **transition_result},
                    attribution=attribution_summary(cfg, "jira"),
                )
            results["transition"] = transition

        return Result(
            operation=self.name,
            success=True,
            data=results,
            attribution=attribution_summary(cfg, "jira"),
        )

    @staticmethod
    def _transition(ticket: str, transition_name: str, cfg: Config) -> dict[str, Any]:
        import httpx

        base = cfg.jira_url.rstrip("/")
        headers = _jira_headers(cfg)

        # Get available transitions
        try:
            resp = httpx.get(
                f"{base}/rest/api/3/issue/{ticket}/transitions",
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            transitions = resp.json().get("transitions", [])
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return {"success": False, "error": str(e)}

        # Find matching transition
        target = None
        for t in transitions:
            if t["name"].lower() == transition_name.lower():
                target = t
                break

        if not target:
            available = [t["name"] for t in transitions]
            return {
                "success": False,
                "error": f"Transition '{transition_name}' not found",
                "available_transitions": available,
            }

        # Execute transition
        try:
            resp = httpx.post(
                f"{base}/rest/api/3/issue/{ticket}/transitions",
                json={"transition": {"id": target["id"]}},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return {"success": False, "error": str(e)}

        return {"success": True, "transition_id": target["id"]}
