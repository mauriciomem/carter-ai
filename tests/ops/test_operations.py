"""Tests for carter-ops CLI and operations."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add ops directory to path
OPS_DIR = Path(__file__).resolve().parent.parent / "ops"
sys.path.insert(0, str(OPS_DIR))


@pytest.fixture(autouse=True)
def _ops_path():
    """Ensure ops dir is on sys.path for all tests."""
    if str(OPS_DIR) not in sys.path:
        sys.path.insert(0, str(OPS_DIR))


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────


class TestConfig:
    def test_load_defaults(self, tmp_path: Path) -> None:
        from config import Config

        cfg = Config.load(tmp_path / "nonexistent.toml")
        assert cfg.bot_name == "carter-bot"
        assert cfg.bot_email == "carter-bot@users.noreply.github.com"

    def test_load_from_toml(self, tmp_path: Path) -> None:
        from config import Config

        toml = tmp_path / "config.toml"
        toml.write_text(
            '[attribution]\n'
            'name = "my-bot"\n'
            'email = "my-bot@example.com"\n'
            '\n'
            '[git]\n'
            f'signing_key = "{tmp_path / "fake_key"}"\n'
        )
        # Create the fake key so validation would pass
        (tmp_path / "fake_key").write_text("fake")

        cfg = Config.load(toml)
        assert cfg.bot_name == "my-bot"
        assert cfg.bot_email == "my-bot@example.com"

    def test_env_vars_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from config import Config

        monkeypatch.setenv("ATLASSIAN_URL", "https://test.atlassian.net")
        monkeypatch.setenv("ATLASSIAN_EMAIL", "test@test.com")
        monkeypatch.setenv("JIRA_TOKEN", "secret123")

        cfg = Config.load(tmp_path / "nonexistent.toml")
        assert cfg.jira_url == "https://test.atlassian.net"
        assert cfg.jira_email == "test@test.com"
        assert cfg.jira_token == "secret123"

    def test_validate_jira_missing(self, tmp_path: Path) -> None:
        from config import Config

        cfg = Config.load(tmp_path / "nonexistent.toml")
        errors = cfg.validate_jira()
        assert len(errors) == 3  # url, email, token all missing


# ──────────────────────────────────────────────────────────────────────────────
# Attribution
# ──────────────────────────────────────────────────────────────────────────────


class TestAttribution:
    def test_git_author(self) -> None:
        from attribution import git_author
        from config import Config

        cfg = Config()
        assert git_author(cfg) == "carter-bot <carter-bot@users.noreply.github.com>"

    def test_append_jira_footer(self) -> None:
        from attribution import append_jira_footer
        from config import Config

        cfg = Config()
        result = append_jira_footer("Status update", cfg)
        assert result.startswith("Status update")
        assert "carter-bot" in result

    def test_attribution_summary_git(self) -> None:
        from attribution import attribution_summary
        from config import Config

        cfg = Config()
        summary = attribution_summary(cfg, "git")
        assert "carter-bot" in summary

    def test_attribution_summary_jira(self) -> None:
        from attribution import attribution_summary
        from config import Config

        cfg = Config()
        summary = attribution_summary(cfg, "jira")
        assert "carter-bot" in summary


# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────


class TestOutput:
    def test_dry_run_output(self) -> None:
        from output import dry_run_output

        result = dry_run_output(
            operation="git-branch",
            steps=["git checkout main", "git checkout -b feature/x"],
            attribution="Author: carter-bot",
            side_effects=["New branch"],
        )
        assert result["phase"] == "dry-run"
        assert result["operation"] == "git-branch"
        assert len(result["steps"]) == 2

    def test_execute_output(self) -> None:
        from output import execute_output

        result = execute_output(
            operation="git-commit",
            success=True,
            result={"commit_sha": "abc123"},
            attribution="Author: carter-bot",
        )
        assert result["phase"] == "execute"
        assert result["success"] is True

    def test_error_output(self) -> None:
        from output import error_output

        result = error_output(
            operation="git-push",
            code="PUSH_REJECTED",
            message="Remote has changes",
            suggestion="Run: git pull",
        )
        assert result["success"] is False
        assert result["error"]["code"] == "PUSH_REJECTED"
        assert result["error"]["suggestion"] == "Run: git pull"

    def test_error_output_no_suggestion(self) -> None:
        from output import error_output

        result = error_output(
            operation="git-push",
            code="PUSH_REJECTED",
            message="Remote has changes",
        )
        assert "suggestion" not in result["error"]


# ──────────────────────────────────────────────────────────────────────────────
# Operation registry
# ──────────────────────────────────────────────────────────────────────────────


class TestOperationRegistry:
    def test_discover_operations(self) -> None:
        from operations import discover_operations, list_operations

        discover_operations()
        ops = list_operations()
        assert "git-branch" in ops
        assert "git-commit" in ops
        assert "git-push" in ops
        assert "git-flow" in ops
        assert "jira-comment" in ops
        assert "jira-create" in ops
        assert "jira-update" in ops

    def test_get_operation(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-branch")
        assert op is not None
        assert op.name == "git-branch"

    def test_get_unknown_operation(self) -> None:
        from operations import get_operation

        assert get_operation("nonexistent") is None


# ──────────────────────────────────────────────────────────────────────────────
# Git operations — dry_run (always safe)
# ──────────────────────────────────────────────────────────────────────────────


class TestGitBranchDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-branch")
        cfg = Config()
        plan = op.dry_run({"name": "feature/test", "from": "main"}, cfg)
        assert plan.operation == "git-branch"
        assert "git checkout -b feature/test" in plan.steps
        assert "feature/test" in plan.side_effects[0]

    def test_validate_missing_name(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-branch")
        errors = op.validate({})
        assert any("--name" in e for e in errors)

    def test_validate_invalid_branch_name(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-branch")
        errors = op.validate({"name": "invalid branch name with spaces"})
        assert any("Invalid" in e for e in errors)


class TestGitCommitDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-commit")
        cfg = Config()
        plan = op.dry_run({"message": "feat: add auth", "files": ["src/auth.py"]}, cfg)
        assert plan.operation == "git-commit"
        assert any("git commit" in s for s in plan.steps)
        assert any("carter-bot" in s for s in plan.steps)

    def test_validate_missing_message(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-commit")
        errors = op.validate({})
        assert any("--message" in e for e in errors)


class TestGitPushDryRun:
    def test_dry_run_with_branch(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-push")
        cfg = Config()
        plan = op.dry_run({"branch": "feature/test"}, cfg)
        assert "git push origin feature/test" in plan.steps


class TestGitFlowDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-flow")
        cfg = Config()
        plan = op.dry_run(
            {"branch": "feature/x", "message": "feat: x", "from": "main"}, cfg,
        )
        assert plan.operation == "git-flow"
        assert len(plan.steps) == 6  # checkout, pull, branch, add, commit, push
        assert len(plan.side_effects) == 3

    def test_validate_missing_params(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("git-flow")
        errors = op.validate({})
        assert any("--branch" in e for e in errors)
        assert any("--message" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────────────
# Jira operations — dry_run (always safe)
# ──────────────────────────────────────────────────────────────────────────────


class TestJiraCommentDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("jira-comment")
        cfg = Config()
        plan = op.dry_run({"ticket": "PROJ-123", "body": "Status update"}, cfg)
        assert plan.operation == "jira-comment"
        assert "PROJ-123" in plan.steps[0]

    def test_validate_missing_ticket(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("jira-comment")
        errors = op.validate({"body": "test"})
        assert any("--ticket" in e for e in errors)

    def test_validate_bad_ticket_format(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("jira-comment")
        errors = op.validate({"ticket": "bad-key", "body": "test"})
        assert any("Invalid" in e for e in errors)


class TestJiraCreateDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("jira-create")
        cfg = Config()
        plan = op.dry_run(
            {"project": "PROJ", "type": "Story", "summary": "Add auth"}, cfg,
        )
        assert plan.operation == "jira-create"
        assert any("PROJ" in s for s in plan.steps)
        assert any("Story" in s for s in plan.steps)

    def test_validate_missing_project(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("jira-create")
        errors = op.validate({"type": "Story", "summary": "test"})
        assert any("--project" in e for e in errors)


class TestJiraUpdateDryRun:
    def test_dry_run_comment_and_transition(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("jira-update")
        cfg = Config()
        plan = op.dry_run(
            {"ticket": "PROJ-123", "comment": "Done", "transition": "Done"}, cfg,
        )
        assert plan.operation == "jira-update"
        assert len(plan.side_effects) == 2

    def test_validate_no_action(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("jira-update")
        errors = op.validate({"ticket": "PROJ-123"})
        assert any("--comment" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────


class TestCLIParsing:
    def test_parse_list(self) -> None:
        from carter_ops import _parse_argv

        op, params, phase = _parse_argv(["--list"])
        assert phase == "list"

    def test_parse_dry_run(self) -> None:
        from carter_ops import _parse_argv

        op, params, phase = _parse_argv(
            ["git-branch", "--name", "feature/test", "--from", "main", "--dry-run"]
        )
        assert op == "git-branch"
        assert params["name"] == "feature/test"
        assert params["from"] == "main"
        assert phase == "dry-run"

    def test_parse_execute(self) -> None:
        from carter_ops import _parse_argv

        op, params, phase = _parse_argv(
            ["git-commit", "--message", "feat: x", "--files", "a.py,b.py", "--execute"]
        )
        assert op == "git-commit"
        assert params["message"] == "feat: x"
        assert params["files"] == ["a.py", "b.py"]
        assert phase == "execute"

    def test_parse_empty(self) -> None:
        from carter_ops import _parse_argv

        op, params, phase = _parse_argv([])
        assert op == ""

    def test_list_operations(self, capsys: pytest.CaptureFixture[str]) -> None:
        from carter_ops import main

        exit_code = main(["--list"])
        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert "git-branch" in output["operations"]
        assert "jira-comment" in output["operations"]

    def test_no_operation_shows_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from carter_ops import main

        exit_code = main([])
        assert exit_code == 1

    def test_no_phase_shows_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from carter_ops import main

        exit_code = main(["git-branch", "--name", "x"])
        assert exit_code == 1

    def test_unknown_operation(self, capsys: pytest.CaptureFixture[str]) -> None:
        from carter_ops import main

        exit_code = main(["nonexistent", "--dry-run"])
        assert exit_code == 1

    def test_validation_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from carter_ops import main

        exit_code = main(["git-branch", "--dry-run"])  # missing --name
        assert exit_code == 1
        output = json.loads(capsys.readouterr().out)
        assert output["success"] is False

    def test_dry_run_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        from carter_ops import main

        exit_code = main(["git-branch", "--name", "feature/test", "--dry-run"])
        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["phase"] == "dry-run"
        assert output["operation"] == "git-branch"


# ──────────────────────────────────────────────────────────────────────────────
# Git operations — execute (with mock subprocess)
# ──────────────────────────────────────────────────────────────────────────────


class TestGitBranchExecute:
    @patch("operations.git_branch.subprocess.run")
    def test_execute_success(self, mock_run: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        discover_operations()
        op = get_operation("git-branch")
        cfg = Config()
        result = op.execute({"name": "feature/test", "from": "main"}, cfg)
        assert result.success is True
        assert result.data["branch"] == "feature/test"
        assert mock_run.call_count == 3  # checkout, pull, checkout -b

    @patch("operations.git_branch.subprocess.run")
    def test_execute_failure(self, mock_run: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="branch already exists"
        )
        discover_operations()
        op = get_operation("git-branch")
        cfg = Config()
        result = op.execute({"name": "feature/test"}, cfg)
        assert result.success is False


class TestGitCommitExecute:
    @patch("operations.git_commit.subprocess.run")
    def test_execute_success(self, mock_run: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[feature/test abc1234] feat: add auth\n 1 file changed",
            stderr="",
        )
        discover_operations()
        op = get_operation("git-commit")
        cfg = Config()
        result = op.execute({"message": "feat: add auth", "files": ["src/auth.py"]}, cfg)
        assert result.success is True
        assert result.data["message"] == "feat: add auth"


class TestGitPushExecute:
    @patch("operations.git_push.subprocess.run")
    def test_execute_success(self, mock_run: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        discover_operations()
        op = get_operation("git-push")
        cfg = Config()
        result = op.execute({"branch": "feature/test"}, cfg)
        assert result.success is True
        assert result.data["branch"] == "feature/test"

    @patch("operations.git_push.subprocess.run")
    def test_execute_rejected(self, mock_run: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="rejected non-fast-forward"
        )
        discover_operations()
        op = get_operation("git-push")
        cfg = Config()
        result = op.execute({"branch": "feature/test"}, cfg)
        assert result.success is False
        assert "suggestion" in result.data


# ──────────────────────────────────────────────────────────────────────────────
# GitHub config
# ──────────────────────────────────────────────────────────────────────────────


class TestGitHubConfig:
    def test_validate_github_missing_token(self, tmp_path: Path) -> None:
        from config import Config

        cfg = Config.load(tmp_path / "nonexistent.toml")
        errors = cfg.validate_github()
        assert any("GITHUB_TOKEN" in e for e in errors)

    def test_validate_github_with_token(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from config import Config

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_testtoken123")
        cfg = Config.load(tmp_path / "nonexistent.toml")
        errors = cfg.validate_github()
        assert errors == []


class TestGitHubAttribution:
    def test_append_github_footer(self) -> None:
        from attribution import append_github_footer
        from config import Config

        cfg = Config()
        result = append_github_footer("Status update", cfg)
        assert result.startswith("Status update")
        assert "carter-bot" in result
        assert "---" in result

    def test_attribution_summary_github(self) -> None:
        from attribution import attribution_summary
        from config import Config

        cfg = Config()
        summary = attribution_summary(cfg, "github")
        assert "carter-bot" in summary


# ──────────────────────────────────────────────────────────────────────────────
# gh-issue
# ──────────────────────────────────────────────────────────────────────────────


class TestGhIssueDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-issue")
        cfg = Config()
        plan = op.dry_run(
            {"repo": "owner/repo", "title": "Bug report", "body": "Details here"},
            cfg,
        )
        assert plan.operation == "gh-issue"
        assert any("owner/repo" in s for s in plan.steps)

    def test_validate_missing_repo(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-issue")
        errors = op.validate({"title": "Test"})
        assert any("--repo" in e for e in errors)

    def test_validate_bad_repo_format(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-issue")
        errors = op.validate({"repo": "noslash", "title": "Test"})
        assert any("owner/repo" in e for e in errors)

    def test_validate_missing_title(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-issue")
        errors = op.validate({"repo": "owner/repo"})
        assert any("--title" in e for e in errors)


class TestGhIssueExecute:
    @patch("httpx.post")
    def test_execute_success(self, mock_post: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "number": 42,
            "html_url": "https://github.com/owner/repo/issues/42",
            "title": "Bug report",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        discover_operations()
        op = get_operation("gh-issue")
        cfg = Config(github_token="ghp_test")
        result = op.execute(
            {"repo": "owner/repo", "title": "Bug report", "body": "Details"},
            cfg,
        )
        assert result.success is True
        assert result.data["number"] == 42

    @patch("httpx.post")
    def test_execute_http_error(self, mock_post: MagicMock) -> None:
        import httpx as _httpx

        from config import Config
        from operations import discover_operations, get_operation

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_post.side_effect = _httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_resp,
        )

        discover_operations()
        op = get_operation("gh-issue")
        cfg = Config(github_token="ghp_test")
        result = op.execute(
            {"repo": "owner/repo", "title": "Bug report"},
            cfg,
        )
        assert result.success is False
        assert "403" in result.data["error"]


# ──────────────────────────────────────────────────────────────────────────────
# gh-issue-comment
# ──────────────────────────────────────────────────────────────────────────────


class TestGhIssueCommentDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-issue-comment")
        cfg = Config()
        plan = op.dry_run(
            {"repo": "owner/repo", "issue": "42", "body": "Looks good"},
            cfg,
        )
        assert plan.operation == "gh-issue-comment"
        assert any("42" in s for s in plan.steps)

    def test_validate_missing_fields(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-issue-comment")
        errors = op.validate({})
        assert len(errors) == 3  # repo, issue, body


class TestGhIssueCommentExecute:
    @patch("httpx.post")
    def test_execute_success(self, mock_post: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": 123,
            "html_url": "https://github.com/owner/repo/issues/42#issuecomment-123",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        discover_operations()
        op = get_operation("gh-issue-comment")
        cfg = Config(github_token="ghp_test")
        result = op.execute(
            {"repo": "owner/repo", "issue": "42", "body": "Looks good"},
            cfg,
        )
        assert result.success is True
        assert result.data["comment_id"] == 123


# ──────────────────────────────────────────────────────────────────────────────
# gh-pr
# ──────────────────────────────────────────────────────────────────────────────


class TestGhPrDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-pr")
        cfg = Config()
        plan = op.dry_run(
            {"repo": "owner/repo", "title": "Add feature", "head": "feature/x", "base": "main"},
            cfg,
        )
        assert plan.operation == "gh-pr"
        assert any("feature/x" in s for s in plan.steps)
        assert any("main" in s for s in plan.steps)

    def test_validate_missing_fields(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-pr")
        errors = op.validate({})
        assert len(errors) == 4  # repo, title, head, base


class TestGhPrExecute:
    @patch("httpx.post")
    def test_execute_success(self, mock_post: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "number": 99,
            "html_url": "https://github.com/owner/repo/pull/99",
            "title": "Add feature",
            "draft": False,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        discover_operations()
        op = get_operation("gh-pr")
        cfg = Config(github_token="ghp_test")
        result = op.execute(
            {"repo": "owner/repo", "title": "Add feature", "head": "feature/x", "base": "main"},
            cfg,
        )
        assert result.success is True
        assert result.data["number"] == 99

    @patch("httpx.post")
    def test_execute_draft(self, mock_post: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "number": 100,
            "html_url": "https://github.com/owner/repo/pull/100",
            "title": "Draft PR",
            "draft": True,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        discover_operations()
        op = get_operation("gh-pr")
        cfg = Config(github_token="ghp_test")
        result = op.execute(
            {"repo": "owner/repo", "title": "Draft PR", "head": "feat/y", "base": "main", "draft": True},
            cfg,
        )
        assert result.success is True
        assert result.data["draft"] is True


# ──────────────────────────────────────────────────────────────────────────────
# gh-pr-comment
# ──────────────────────────────────────────────────────────────────────────────


class TestGhPrCommentDryRun:
    def test_dry_run(self) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-pr-comment")
        cfg = Config()
        plan = op.dry_run(
            {"repo": "owner/repo", "pr": "99", "body": "LGTM"},
            cfg,
        )
        assert plan.operation == "gh-pr-comment"
        assert any("99" in s for s in plan.steps)

    def test_validate_missing_fields(self) -> None:
        from operations import discover_operations, get_operation

        discover_operations()
        op = get_operation("gh-pr-comment")
        errors = op.validate({})
        assert len(errors) == 3  # repo, pr, body


class TestGhPrCommentExecute:
    @patch("httpx.post")
    def test_execute_success(self, mock_post: MagicMock) -> None:
        from config import Config
        from operations import discover_operations, get_operation

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": 456,
            "html_url": "https://github.com/owner/repo/pull/99#issuecomment-456",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        discover_operations()
        op = get_operation("gh-pr-comment")
        cfg = Config(github_token="ghp_test")
        result = op.execute(
            {"repo": "owner/repo", "pr": "99", "body": "LGTM"},
            cfg,
        )
        assert result.success is True
        assert result.data["comment_id"] == 456


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands: audit and config
# ──────────────────────────────────────────────────────────────────────────────


class TestAuditSubcommand:
    def test_audit_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import carter_ops

        # Redirect audit log to tmp
        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")

        rc = carter_ops.main([
            "audit",
            "--operation", "git-flow",
            "--params", '{"branch": "feature/x", "message": "feat: x"}',
            "--result", "success",
            "--identifiers", '{"commit_sha": "abc1234"}',
        ])
        assert rc == 0

        # Verify audit log was written
        log_content = (tmp_path / "audit.log").read_text()
        import json
        entry = json.loads(log_content.strip())
        assert entry["operation"] == "git-flow"
        assert entry["result"] == "success"
        assert entry["identifiers"]["commit_sha"] == "abc1234"
        assert entry["params"]["branch"] == "feature/x"

    def test_audit_missing_operation(self, capsys: pytest.CaptureFixture) -> None:
        import carter_ops

        rc = carter_ops.main(["audit", "--result", "success"])
        assert rc == 1

    def test_audit_missing_result(self, capsys: pytest.CaptureFixture) -> None:
        import carter_ops

        rc = carter_ops.main(["audit", "--operation", "git-flow"])
        assert rc == 1

    def test_audit_minimal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")

        rc = carter_ops.main([
            "audit",
            "--operation", "git-push",
            "--result", "failure",
        ])
        assert rc == 0

        import json
        entry = json.loads((tmp_path / "audit.log").read_text().strip())
        assert entry["operation"] == "git-push"
        assert entry["result"] == "failure"


class TestConfigSubcommand:
    def test_config_emit(self, capsys: pytest.CaptureFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import carter_ops

        # Create a test config file
        config_toml = tmp_path / "config.toml"
        config_toml.write_text(
            '[attribution]\n'
            'name = "test-bot"\n'
            'email = "test-bot@example.com"\n'
            'footer = "Generated by test-bot."\n'
            '\n'
            '[git]\n'
            'signing_key = ""\n'
        )

        # Monkey-patch Config.load to use our test config
        from config import Config
        original_load = Config.load

        @classmethod
        def mock_load(cls, config_path=None):
            return original_load(config_toml)

        monkeypatch.setattr(Config, "load", mock_load)

        rc = carter_ops.main(["config", "--emit"])
        assert rc == 0

        import json
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["bot_name"] == "test-bot"
        assert data["bot_email"] == "test-bot@example.com"

    def test_config_no_flag(self, capsys: pytest.CaptureFixture) -> None:
        import carter_ops

        rc = carter_ops.main(["config"])
        assert rc == 1
