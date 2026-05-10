# /// script
# requires-python = ">=3.11"
# ///
"""carter-ops: git-branch — create a feature branch."""
from __future__ import annotations

import re
import subprocess
from typing import Any

from attribution import attribution_summary
from config import Config
from operations import Operation, Plan, Result, register


@register
class GitBranch(Operation):
    name = "git-branch"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("name"):
            errors.append("--name is required")
        else:
            name = params["name"]
            if not re.match(r"^[\w./-]+$", name):
                errors.append(f"Invalid branch name: {name}")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        name = params["name"]
        from_branch = params.get("from", "main")
        steps = [
            f"git checkout {from_branch}",
            f"git pull origin {from_branch}",
            f"git checkout -b {name}",
        ]
        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "git"),
            side_effects=[f"New branch '{name}' created from '{from_branch}'"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        name = params["name"]
        from_branch = params.get("from", "main")

        try:
            subprocess.run(
                ["git", "checkout", from_branch],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "pull", "origin", from_branch],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "checkout", "-b", name],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            return Result(
                operation=self.name,
                success=False,
                data={"error": e.stderr.strip(), "returncode": e.returncode},
                attribution=attribution_summary(cfg, "git"),
            )

        return Result(
            operation=self.name,
            success=True,
            data={"branch": name, "from": from_branch},
            attribution=attribution_summary(cfg, "git"),
        )
