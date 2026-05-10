# /// script
# requires-python = ">=3.11"
# ///
"""carter-ops: git-flow — composite: branch → add → commit → push."""
from __future__ import annotations

from typing import Any

from attribution import attribution_summary, git_author
from config import Config
from operations import Operation, Plan, Result, register
from operations.git_branch import GitBranch
from operations.git_commit import GitCommit
from operations.git_push import GitPush


@register
class GitFlow(Operation):
    name = "git-flow"

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors = []
        if not params.get("branch"):
            errors.append("--branch is required")
        if not params.get("message"):
            errors.append("--message is required")
        return errors

    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        branch_name = params["branch"]
        from_branch = params.get("from", "main")
        message = params["message"]
        files = params.get("files", ["."])
        if isinstance(files, str):
            files = [files]
        author = git_author(cfg)
        file_list = " ".join(files)

        steps = [
            f"git checkout {from_branch}",
            f"git pull origin {from_branch}",
            f"git checkout -b {branch_name}",
            f"git add {file_list}",
            f"git commit --author='{author}' -S -m '{message}'",
            f"git push origin {branch_name}",
        ]
        return Plan(
            operation=self.name,
            steps=steps,
            attribution=attribution_summary(cfg, "git"),
            side_effects=[
                f"New branch '{branch_name}' from '{from_branch}'",
                f"1 new commit as {cfg.bot_name}",
                f"Branch pushed to origin",
            ],
        )

    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        branch_name = params["branch"]
        from_branch = params.get("from", "main")
        message = params["message"]
        files = params.get("files", ["."])

        # Step 1: branch
        branch_op = GitBranch()
        branch_result = branch_op.execute(
            {"name": branch_name, "from": from_branch}, cfg,
        )
        if not branch_result.success:
            return Result(
                operation=self.name,
                success=False,
                data={"failed_step": "git-branch", **branch_result.data},
                attribution=attribution_summary(cfg, "git"),
            )

        # Step 2: commit
        commit_op = GitCommit()
        commit_result = commit_op.execute(
            {"message": message, "files": files}, cfg,
        )
        if not commit_result.success:
            return Result(
                operation=self.name,
                success=False,
                data={"failed_step": "git-commit", **commit_result.data},
                attribution=attribution_summary(cfg, "git"),
            )

        # Step 3: push
        push_op = GitPush()
        push_result = push_op.execute({"branch": branch_name}, cfg)
        if not push_result.success:
            return Result(
                operation=self.name,
                success=False,
                data={"failed_step": "git-push", **push_result.data},
                attribution=attribution_summary(cfg, "git"),
            )

        return Result(
            operation=self.name,
            success=True,
            data={
                "branch": branch_name,
                "from": from_branch,
                "commit_sha": commit_result.data.get("commit_sha", ""),
                "pushed": True,
            },
            attribution=attribution_summary(cfg, "git"),
        )
