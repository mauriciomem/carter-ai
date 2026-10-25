"""Tests for the carter-ops CLI (audit ledger, policy-override, config --emit)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────


class TestConfig:
    def test_load_defaults(self, tmp_path: Path) -> None:
        from carter.ops.config import Config

        cfg = Config.load(tmp_path / "nonexistent.toml")
        assert cfg.bot_name == "carter-bot"
        assert cfg.bot_email == "carter-bot@users.noreply.github.com"

    def test_load_from_toml(self, tmp_path: Path) -> None:
        from carter.ops.config import Config

        toml = tmp_path / "config.toml"
        toml.write_text(
            "[attribution]\n"
            'name = "my-bot"\n'
            'email = "my-bot@example.com"\n'
            "\n"
            "[git]\n"
            f'signing_key = "{tmp_path / "fake_key"}"\n'
        )
        # Create the fake key so validation would pass
        (tmp_path / "fake_key").write_text("fake")

        cfg = Config.load(toml)
        assert cfg.bot_name == "my-bot"
        assert cfg.bot_email == "my-bot@example.com"

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
                "git push origin main",
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
        assert entry["action"] == "git push origin main"
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
                    "git push",
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
    def test_config_emit(
        self, capsys: pytest.CaptureFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from carter.ops import carter_ops

        # Create a test config file
        config_toml = tmp_path / "config.toml"
        config_toml.write_text(
            "[attribution]\n"
            'name = "test-bot"\n'
            'email = "test-bot@example.com"\n'
            'footer = "Generated by test-bot."\n'
            "\n"
            "[git]\n"
            'signing_key = ""\n'
        )

        # Monkey-patch Config.load to use our test config
        from carter.ops.config import Config

        original_load = Config.load

        @classmethod
        def mock_load(cls, config_path=None):
            return original_load(config_toml)

        monkeypatch.setattr(Config, "load", mock_load)

        rc = carter_ops.main(["config", "--emit"])
        assert rc == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["bot_name"] == "test-bot"
        assert data["bot_email"] == "test-bot@example.com"

    def test_config_no_flag(self, capsys: pytest.CaptureFixture) -> None:
        from carter.ops import carter_ops

        rc = carter_ops.main(["config"])
        assert rc == 1
