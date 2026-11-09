"""Tests for the carter-ops CLI (audit ledger, policy-override, config --emit)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────


class TestConfig:
    def test_load_defaults_are_t0_with_no_invented_identity(self, tmp_path: Path) -> None:
        from carter.ops.config import Config

        cfg = Config.load(tmp_path / "nonexistent.toml")
        assert cfg.tier == "t0"
        assert cfg.coauthor_trailer == "Assisted-by: Carter"
        assert cfg.footer == "_This comment was generated with Carter._"
        assert not hasattr(cfg, "bot_email") and not hasattr(cfg, "bot_name")

    def test_load_t1_identity_from_schema_2(self, tmp_path: Path) -> None:
        from carter.ops.config import Config

        toml = tmp_path / "config.toml"
        toml.write_text(
            'schema = 2\n[identity]\nlogin = "my-bot"\nid = 7\n'
            'email = "7+my-bot@users.noreply.github.com"\n'
        )
        cfg = Config.load(toml)
        assert cfg.coauthor_trailer == "Co-authored-by: my-bot <7+my-bot@users.noreply.github.com>"

    def test_env_vars_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from carter.ops.config import Config

        monkeypatch.setenv("GITHUB_TOKEN", "secret123")

        cfg = Config.load(tmp_path / "nonexistent.toml")
        assert cfg.github_token == "secret123"


# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing + dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestParseFlags:
    def test_key_value_pairs(self) -> None:
        from carter.ops.carter_ops import _parse_flags

        assert _parse_flags(["--operation", "git-flow", "--result", "success"]) == {
            "operation": "git-flow",
            "result": "success",
        }

    def test_bare_flag_is_true(self) -> None:
        from carter.ops.carter_ops import _parse_flags

        assert _parse_flags(["--emit"]) == {"emit": True}

    def test_stray_positional_ignored(self) -> None:
        from carter.ops.carter_ops import _parse_flags

        assert _parse_flags(["stray", "--a", "1"]) == {"a": "1"}


class TestDispatch:
    def test_missing_subcommand(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        assert carter_ops.main([]) == 1
        assert "Usage" in capsys.readouterr().err

    def test_unknown_subcommand(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        # The legacy --dry-run/--execute operations were removed.
        assert carter_ops.main(["git-flow", "--branch", "x", "--dry-run"]) == 1
        assert "Unknown subcommand: git-flow" in capsys.readouterr().err


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands: audit, policy-override, config
# ──────────────────────────────────────────────────────────────────────────────


class TestAuditSubcommand:
    def test_audit_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from carter.ops import carter_ops

        # Redirect audit log to tmp
        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")

        rc = carter_ops.main(
            [
                "audit",
                "--operation",
                "git-flow",
                "--params",
                '{"branch": "feature/x", "message": "feat: x"}',
                "--result",
                "success",
                "--identifiers",
                '{"commit_sha": "abc1234"}',
            ]
        )
        assert rc == 0

        # Verify audit log was written
        log_content = (tmp_path / "audit.log").read_text()
        entry = json.loads(log_content.strip())
        assert entry["operation"] == "git-flow"
        assert entry["result"] == "success"
        assert entry["identifiers"]["commit_sha"] == "abc1234"
        assert entry["params"]["branch"] == "feature/x"

    def test_audit_prints_nothing_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        assert carter_ops.main(["audit", "--operation", "git-flow", "--result", "success"]) == 0
        assert capsys.readouterr().out == ""  # no JSON echo for the agent to repeat

    def test_audit_missing_operation(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(["audit", "--result", "success"])
        assert rc == 1

    def test_audit_missing_result(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(["audit", "--operation", "git-flow"])
        assert rc == 1

    def test_audit_minimal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")

        rc = carter_ops.main(
            [
                "audit",
                "--operation",
                "git-push",
                "--result",
                "failure",
            ]
        )
        assert rc == 0

        entry = json.loads((tmp_path / "audit.log").read_text().strip())
        assert entry["operation"] == "git-push"
        assert entry["result"] == "failure"


class TestPolicyOverrideSubcommand:
    """The single-action override ledger.

    Override != authorization — the ledger RECORDS a deliberate override of a
    policy gate; it cannot lift a platform deny. One entry per action; no
    blanket/session-wide overrides.
    """

    def test_override_logs_one_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        rc = carter_ops.main(
            [
                "policy-override",
                "--category",
                "remote-write",
                "--action",
                "vault read secret/app",
                "--tier",
                "native-ask",
                "--reason",
                "hotfix release",
            ]
        )
        assert rc == 0

        lines = (tmp_path / "audit.log").read_text().strip().splitlines()
        assert len(lines) == 1  # exactly one entry per action — not session-wide
        entry = json.loads(lines[0])
        assert entry["event"] == "policy-override"
        assert entry["category"] == "remote-write"
        assert entry["action"] == "vault read secret/app"
        assert entry["tier"] == "native-ask"
        assert entry["reason"] == "hotfix release"
        # Honesty: the ledger records, it does not authorize/lift a deny.
        assert entry["authorized"] is False

    def test_override_requires_category(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(["policy-override", "--action", "x", "--tier", "native-ask"])
        assert rc == 1

    def test_override_requires_action(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(
            ["policy-override", "--category", "remote-write", "--tier", "native-ask"]
        )
        assert rc == 1

    def test_override_rejects_unknown_category(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        rc = carter_ops.main(
            ["policy-override", "--category", "R2", "--action", "x", "--tier", "native-ask"]
        )
        assert rc == 1
        assert "--category must be one of: read, local-write, remote-write, dangerous" in (
            capsys.readouterr().err
        )
        assert not (tmp_path / "audit.log").exists()

    @pytest.mark.parametrize("flag", ["--action", "--reason"])
    def test_override_rejects_overlong_text(
        self,
        flag: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        args = {"--category": "dangerous", "--action": "x", "--tier": "native-ask"}
        args[flag] = "a" * (carter_ops.MAX_TEXT_LEN + 1)
        rc = carter_ops.main(["policy-override", *[t for kv in args.items() for t in kv]])
        assert rc == 1
        assert "too long" in capsys.readouterr().err
        assert not (tmp_path / "audit.log").exists()

    def test_override_accepts_text_at_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        reason = "r" * carter_ops.MAX_TEXT_LEN
        rc = carter_ops.main(
            [
                "policy-override",
                "--category",
                "dangerous",
                "--action",
                "x",
                "--tier",
                "native-ask",
                "--reason",
                reason,
            ]
        )
        assert rc == 0

    def test_override_rejects_unknown_tier(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(
            [
                "policy-override",
                "--category",
                "remote-write",
                "--action",
                "x",
                "--tier",
                "blanket",
            ]
        )
        assert rc == 1

    def test_override_native_deny_records_not_authorizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        rc = carter_ops.main(
            [
                "policy-override",
                "--category",
                "dangerous",
                "--action",
                "terraform apply",
                "--tier",
                "native-deny",
                "--reason",
                "approved exception",
            ]
        )
        assert rc == 0

        entry = json.loads((tmp_path / "audit.log").read_text().strip())
        assert entry["tier"] == "native-deny"
        # Even at native-deny the ledger only records — it cannot lift the deny.
        assert entry["authorized"] is False

    def test_two_overrides_are_two_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        for _ in range(2):
            carter_ops.main(
                [
                    "policy-override",
                    "--category",
                    "remote-write",
                    "--action",
                    "vault write secret/app",
                    "--tier",
                    "native-ask",
                ]
            )
        lines = (tmp_path / "audit.log").read_text().strip().splitlines()
        assert len(lines) == 2  # per-action, never a session-wide blanket

    def test_prose_backstop_tier_records_unauthorized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        rc = carter_ops.main(
            [
                "policy-override",
                "--category",
                "remote-write",
                "--action",
                "post release notes",
                "--tier",
                "prose-backstop",
                "--reason",
                "advisory-only target",
            ]
        )
        assert rc == 0

        entry = json.loads((tmp_path / "audit.log").read_text().strip())
        assert entry["tier"] == "prose-backstop"
        # The weakest tier still only records — it never authorizes.
        assert entry["authorized"] is False


class TestConfigSubcommand:
    def test_config_emit(self, capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(["config", "--emit"])
        assert rc == 0

        data = json.loads(capsys.readouterr().out)
        assert data["tier"] == "t0"
        assert data["commits"] == "allowed"
        assert data["coauthor_trailer"] == "Assisted-by: Carter"

    def test_config_no_flag(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(["config"])
        assert rc == 1


class TestHelp:
    @pytest.mark.parametrize(
        "argv", [["--help"], ["-h"], ["help"], ["audit", "--help"], ["config", "-h"]]
    )
    def test_help_exits_zero(self, argv: list[str], capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        assert carter_ops.main(argv) == 0
        out = capsys.readouterr()
        assert "Usage: carter ops" in out.out
        assert out.err == ""

    def test_cli_ops_help(self) -> None:
        from click.testing import CliRunner

        from carter.cli import main

        result = CliRunner().invoke(main, ["ops", "--help"])
        assert result.exit_code == 0
        assert "Usage: carter ops" in result.output


class TestPolicyOverrideRefusesGithubWrites:
    """every GitHub write is human-only, so the override ledger
    cannot be used to weaken it. The refusal points at `carter push` and is itself audited."""

    GITHUB_WRITES = [
        "git push",
        "git push origin main",
        "git push --force origin main",
        "git send-pack origin main",
        "git -C repo push",
        "gh pr merge 3",
        "gh pr close 3",
        "gh pr review 3",
        "gh pr ready 3",
        "gh issue create",
        "gh issue comment 4",
        "gh issue edit 4",
        "gh release create v1",
        "gh api repos/o/r/issues",
        "gh api -X POST /x",
        "GH PR MERGE",
        "  git   push  ",
        "run: git push && echo done",
    ]
    ALLOWED = [
        "vault read secret/app",
        "terraform apply",
        "post release notes in Slack",
        "add a Jira comment",
        "gh pr view 3",
        "gh pr create --title x",  # opening, editing and commenting are allowed
        "gh pr edit 3",
        "gh pr comment 3",
        "gh issue list",
        "git pull origin main",
        "git status",
        "push notifications to staging",
    ]

    def run(self, action: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **flags: str):
        from carter.ops import carter_ops

        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "audit.log")
        argv = ["policy-override", "--category", flags.get("category", "remote-write"),
                "--action", action, "--tier", flags.get("tier", "native-ask")]  # fmt: skip
        return carter_ops.main(argv)

    @pytest.mark.parametrize("action", GITHUB_WRITES)
    @pytest.mark.parametrize("tier", ["native-deny", "native-ask", "prose-backstop"])
    def test_github_writes_are_refused_at_every_tier(
        self, action: str, tier: str, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        assert self.run(action, tmp_path, monkeypatch, tier=tier) == 1
        err = capsys.readouterr().err
        assert "carter push" in err and "!carter push" in err and "carter pr" not in err

    @pytest.mark.parametrize("category", ["read", "local-write", "remote-write", "dangerous"])
    def test_the_category_does_not_matter(self, category: str, tmp_path, monkeypatch) -> None:
        assert self.run("git push", tmp_path, monkeypatch, category=category) == 1

    @pytest.mark.parametrize("action", ALLOWED)
    def test_other_overrides_still_work(self, action: str, tmp_path, monkeypatch) -> None:
        assert self.run(action, tmp_path, monkeypatch) == 0

    def test_the_refusal_is_recorded_in_the_audit_log_and_never_authorizes(
        self, tmp_path, monkeypatch
    ) -> None:
        self.run("git push --force origin main", tmp_path, monkeypatch)
        (line,) = (tmp_path / "audit.log").read_text().strip().splitlines()
        entry = json.loads(line)
        assert entry["event"] == "policy-override-refused"
        assert entry["authorized"] is False and entry["action"] == "git push --force origin main"
        assert entry["category"] == "remote-write"

    def test_a_refusal_prints_nothing_on_stdout(self, tmp_path, monkeypatch, capsys) -> None:
        self.run("gh pr merge 3", tmp_path, monkeypatch)
        assert capsys.readouterr().out == ""

    def test_the_refusal_text_is_the_own_terminal_constant(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        from carter.aplus.push import OWN_TERMINAL

        self.run("git push", tmp_path, monkeypatch)
        assert OWN_TERMINAL in capsys.readouterr().err

    def test_the_matching_list_comes_from_the_rule_tables(self) -> None:
        from carter.config import _BASH_COMMANDS
        from carter.ops import carter_ops

        for pattern in _BASH_COMMANDS["github-write"]:
            assert carter_ops.is_github_write(pattern.removesuffix(" *")), pattern
        assert carter_ops.is_github_write("git send-pack")  # from the push-verbs class
