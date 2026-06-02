# /// script
# requires-python = ">=3.11"
# ///
"""carter-ops: git-push — push branch to remote."""
from __future__ import annotations

import subprocess
from typing import Any

from carter.ops.attribution import attribution_summary
from carter.ops.config import Config
from carter.ops.operations import Operation, Plan, Result, register


@register
class GitPush(Operation):
    name = "git-push"

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        branch = params.get("branch", "")
        if not branch:
            branch = self._current_branch()
        steps = [f"git push origin {branch}"]
        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "git"),
            side_effects=[f"Branch '{branch}' pushed to origin"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        branch = params.get("branch", "")
        if not branch:
            branch = self._current_branch()

        try:
            subprocess.run(
                ["git", "push", "origin", branch],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            suggestion = ""
            stderr = e.stderr.strip()
            if "rejected" in stderr or "non-fast-forward" in stderr:
                suggestion = f"Run: git pull origin {branch} --rebase"
            return Result(
                operation=self.name,
                success=False,
                data={
                    "error": stderr,
                    "returncode": e.returncode,
                    "suggestion": suggestion,
                },
                attribution=attribution_summary(cfg, "git"),
            )

        return Result(
            operation=self.name,
            success=True,
            data={"branch": branch, "remote": "origin"},
            attribution=attribution_summary(cfg, "git"),
        )

    @staticmethod
    def _current_branch() -> str:
        try:
            r = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, check=True,
            )
            return r.stdout.strip()
        except subprocess.CalledProcessError:
            return "HEAD"
