# /// script
# requires-python = ">=3.11"
# ///
"""carter-ops: git-commit — stage files and commit as carter-bot."""
from __future__ import annotations

import subprocess
from typing import Any

from carter.ops.attribution import attribution_summary, git_author
from carter.ops.config import Config
from carter.ops.operations import Operation, Plan, Result, register


@register
class GitCommit(Operation):
    name = "git-commit"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("message"):
            errors.append("--message is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        message = params["message"]
        files = params.get("files", ["."])
        if isinstance(files, str):
            files = [files]

        author = git_author(cfg)
        file_list = " ".join(files)
        steps = [
            f"git add {file_list}",
            f"git commit --author='{author}' -S -m '{message}'",
        ]
        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "git"),
            side_effects=[f"1 new commit on current branch"],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        message = params["message"]
        files = params.get("files", ["."])
        if isinstance(files, str):
            files = [files]

        author = git_author(cfg)

        try:
            subprocess.run(
                ["git", "add"] + files,
                check=True, capture_output=True, text=True,
            )

            cmd = [
                "git", "commit",
                f"--author={author}",
                "-m", message,
            ]
            # Only sign if signing key exists
            if cfg.signing_key:
                cmd.insert(2, "-S")

            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True,
            )

            # Extract commit SHA
            sha = ""
            for line in result.stdout.splitlines():
                if line.strip().startswith("["):
                    parts = line.split()
                    for p in parts:
                        if len(p) >= 7 and all(c in "0123456789abcdef" for c in p.rstrip("]")):
                            sha = p.rstrip("]")
                            break

            # Get SHA from rev-parse as fallback
            if not sha:
                rev = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True,
                )
                sha = rev.stdout.strip()

            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True,
            ).stdout.strip()

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
            data={
                "commit_sha": sha,
                "branch": branch,
                "files_committed": len(files),
                "message": message,
            },
            attribution=attribution_summary(cfg, "git"),
        )
