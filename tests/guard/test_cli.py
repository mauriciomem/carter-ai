"""``carter guard install | status | remove``.

Everything runs under the sandbox home with ``fake_opencode``; the real OpenCode config and
``~/.carter`` are never reachable (the session-end host guard would fail the run)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from carter.cli import main
from carter.guard import gitconfig as gc
from carter.guard import hooks
from carter.guard.alias import ALIAS_KEY
from carter.guard.state import load
from carter.identity.errors import E_HUMAN_TERMINAL, E_POLICIES_MISSING, E_STATE_INVALID, registry
from carter.identity.policyset import policy_statements
from carter.install.mcp import config_target
from carter.install.paths import backups_dir, carter_gitconfig_path, guard_state_path
from guard.conftest import REAL_GIT
from guard.helpers import STAND_IN, agents_json, debug_config, decline, tree_hash, verbose

BUILTINS = ["build", "plan", "general", "explore"]
PAT_MESSAGE = (
    "`~/.carter/secrets/gh-read.token` kept; delete it and revoke the token on GitHub if unused"
)


def _raises(exc: Exception):
    def fail(*_a: object, **_k: object) -> None:
        raise exc

    return fail


SYNTHETIC = Path(__file__).resolve().parents[1] / "data" / "opencode-config-shape.jsonc"


def guard(*args: str, input: str | None = None) -> Result:
    return CliRunner().invoke(main, ["guard", *verbose(args)], input=input, catch_exceptions=False)


def install_all(stack) -> Result:
    stack.fake()
    res = guard("install", "--yes")
    assert res.exit_code == 0, res.output
    return res


def config_data() -> dict:
    return json.loads(config_target(None).read_text())


class TestWhoMayRun:
    @pytest.mark.parametrize("cmd", ["install", "remove"])
    def test_an_agent_shell_is_refused_with_the_registry_text(
        self, cmd, stack, monkeypatch, human_tty
    ) -> None:
        human_tty(True)
        monkeypatch.setenv("AGENT", "x")
        stack.fake()
        before = tree_hash(stack.home)
        res = guard(cmd, "--yes")
        assert res.exit_code == 1
        assert E_HUMAN_TERMINAL in res.output
        assert registry()[E_HUMAN_TERMINAL].message in res.output
        assert tree_hash(stack.home) == before

    def test_status_and_dry_run_are_allowed_in_an_agent_shell(self, stack, monkeypatch) -> None:
        monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_1")
        stack.fake()
        assert guard("status").exit_code == 0
        assert guard("install", "--dry-run").exit_code == 0

    def test_a_non_tty_install_without_yes_is_skipped_with_a_notice_and_exit_0(
        self, stack, human_tty
    ) -> None:
        human_tty(False)
        stack.fake()
        before = tree_hash(stack.home)
        res = guard("install")
        assert res.exit_code == 0
        assert "NOT installed" in res.output and "--yes" not in res.output.replace("no --yes", "")
        assert tree_hash(stack.home) == before
        assert not guard_state_path(None).exists() and not config_target(None).exists()
        assert not backups_dir(None).exists()

    def test_remove_needs_no_terminal_and_asks_nothing(self, stack, human_tty) -> None:
        human_tty(False)  # we have backups, so there is nothing to confirm
        install_all(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove")
        assert res.exit_code == 0, res.output
        assert not guard_state_path(None).exists()

    def test_yes_is_the_scripted_path_without_a_tty(self, stack, human_tty) -> None:
        human_tty(False)
        stack.fake()
        assert guard("install", "--yes").exit_code == 0


class TestDryRun:
    def test_shows_groups_statements_and_per_agent_denies_and_writes_nothing(
        self, stack, human_tty, fake_opencode
    ) -> None:
        # `debug config` is left unconfigured: a dry run must never call it.
        bindir = fake_opencode(agents_output=agents_json(*BUILTINS, "carter-engineer"))
        (bindir / "git").symlink_to(REAL_GIT)  # the dry run probes git for the hook groups
        before = tree_hash(stack.home)
        res = guard("install", "--dry-run")
        assert res.exit_code == 0, res.output
        out = res.output
        assert "dry run" in out
        for group in ("g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit"):
            assert f"{group:<18} would ask" in out
        assert f"{'alias':<18} optional, not part of --yes" in out
        assert f"{'repo_hooks':<18} not on this machine: not needed" in out  # git >= 2.54 here
        assert "Carter agents would carry" in out and "guard rule(s)" in out
        assert "+ deny-git-push" not in out  # no global policies any more
        assert "per-agent denies for built-in agents: build, plan, general, explore" in out
        assert "carter-engineer" not in out
        assert "guard script:" in out and "(would be written)" in out
        assert "would write" in out and "isolation.json" in out and "plugins/carter/index.ts" in out
        assert tree_hash(stack.home) == before
        for path in (guard_state_path(None), config_target(None), backups_dir(None)):
            assert not path.exists()

    def test_only_limits_the_preview(self, stack) -> None:
        stack.fake()
        out = guard("install", "--dry-run", "--only", "sudo-docker").output
        assert "would carry 2 guard rule(s)" in out and "deny-git-push" not in out  # sudo, docker
        assert "per-agent" not in out

    def test_a_declined_group_stays_declined_in_the_preview(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        decline("sudo-docker")
        guard("install", "--yes")
        out = guard("install", "--dry-run").output
        assert "sudo-docker" in out and "declined earlier" in out

    def test_a_real_config_shape_gets_a_readable_diff_and_is_not_touched(self, stack) -> None:
        target = config_target(None)
        target.parent.mkdir(parents=True)
        shutil.copy(SYNTHETIC, target)
        before = target.read_bytes()
        stack.fake()
        res = guard("install", "--dry-run")
        assert res.exit_code == 0
        assert "  + per-agent deny build:carter_push" in res.output
        assert "has comments and rewriting drops them" in res.output
        assert target.read_bytes() == before
        assert not target.with_name(target.name + ".carter-backup").exists()

    def test_a_second_dry_run_after_installing_shows_no_change(self, stack) -> None:
        install_all(stack)
        stack.fake(before=debug_config(stack.live))
        out = guard("install", "--dry-run").output
        assert "already up to date" in out and "  + " not in out

    def test_agents_that_cannot_be_listed_only_warn(self, stack, fake_opencode) -> None:
        fake_opencode(agents_output="boom", agents_exit=1)
        res = guard("install", "--dry-run")
        assert res.exit_code == 0 and "cannot list OpenCode's agents" in res.output


class TestInstall:
    def test_with_consent_everything_is_written_and_recorded(self, stack) -> None:
        res = install_all(stack)
        cfg = config_data()
        assert "policies" not in cfg  # the deny set lives in the Carter agents
        assert sorted(cfg["agents"]) == sorted(BUILTINS)  # not carter-engineer
        for name in BUILTINS:
            actions = [r["action"] for r in cfg["agents"][name]["permissions"]]
            assert actions == ["carter_push"]
        state = load(guard_state_path(None))
        assert sorted(g for g, c in state.consents.items() if c["decision"] == "accepted") == [
            "config-edit", "g2", "hooks", "read-edit-denies", "sudo-docker",
        ]  # fmt: skip
        assert state.opencode_policies == [] and len(state.agent_permissions) == 4
        assert state.opencode_config == str(config_target(None))
        assert state.gitconfig is not None and state.guard_version == hooks.GUARD_VERSION
        assert sorted(Path(f["path"]).name for f in state.files) == [
            "broker.ts", "carter-guard", "core.ts", "gitconfig", "index.ts", "isolation.json",
            "opencode-headless.json",
        ]  # fmt: skip
        assert stat.S_IMODE(guard_state_path(None).stat().st_mode) == 0o600
        assert "plugin installed:" in res.output and "restart the OpenCode server" in res.output
        assert "git config: 8 key(s), mode include" in res.output

    def test_the_hooks_group_writes_the_script_the_gitconfig_and_one_include_line(
        self, stack, home: Path
    ) -> None:
        before = Path(os.environ["GIT_CONFIG_GLOBAL"]).read_text()
        install_all(stack)
        script = hooks.script_path(None)
        assert stat.S_IMODE(script.stat().st_mode) == 0o755
        got = subprocess.run(
            ["git", "config", "--file", str(carter_gitconfig_path(None)), "--get-all",
             "hook.carter-guard-pre-push.command"],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        assert got.rstrip("\n") == hooks.hook_command(script)  # `;` and `#` survive the file
        assert Path(os.environ["GIT_CONFIG_GLOBAL"]).read_text() == (
            before + f"[include]\n\tpath = {carter_gitconfig_path(None)}\n"
        )
        state = load(guard_state_path(None))
        assert state.gitconfig == {
            "file": os.environ["GIT_CONFIG_GLOBAL"],
            "key": "include.path",
            "value": str(carter_gitconfig_path(None)),
        }

    def test_a_second_run_changes_nothing(self, stack) -> None:
        install_all(stack)
        files = (config_target(None).read_bytes(), guard_state_path(None).read_bytes())
        stack.fake(before=debug_config(stack.live))
        res = guard("install", "--yes")
        assert res.exit_code == 0 and "already up to date" in res.output
        assert (config_target(None).read_bytes(), guard_state_path(None).read_bytes()) == files

    def test_a_tty_gets_one_question_with_a_short_summary(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = CliRunner().invoke(main, ["guard", "install"], input="y\n")  # no -v
        assert res.exit_code == 0, res.output
        assert res.output.count("Install?") == 1 and "[Y/n]" in res.output
        assert "Install this group?" not in res.output
        head = res.output.split("Install?")[0]
        assert len([ln for ln in head.splitlines() if ln.strip()]) <= 6  # a short summary
        assert "Carter will set up: g2, hooks, sudo-docker" in head
        state = load(guard_state_path(None))
        assert {"g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit"} <= set(
            state.consents
        )
        assert all(r["decision"] == "accepted" for r in state.consents.values())
        assert "alias" not in state.consents  # optional: only --only brings it
        assert res.output.splitlines()[-1].startswith("✓ guards installed")

    def test_enter_is_yes_and_no_installs_nothing(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        before = tree_hash(stack.home)
        no = guard("install", input="n\n")
        assert no.exit_code == 0 and "Nothing installed" in no.output
        assert tree_hash(stack.home) == before and not guard_state_path(None).exists()
        assert guard("install", input="\n").exit_code == 0
        assert load(guard_state_path(None)).consents

    def test_yes_skips_the_question(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", "--yes")  # no input: a question would abort
        assert res.exit_code == 0 and "Install?" not in res.output

    def test_a_declined_group_stays_declined_and_is_not_asked_again(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        decline("sudo-docker")
        res = guard("install", input="y\n")
        assert res.exit_code == 0, res.output
        state = load(guard_state_path(None))
        assert state.consents["sudo-docker"]["decision"] == "declined"
        assert "sudo-docker" not in res.output.split("Install?")[0].split("up: ")[1].split("\n")[0]

    def test_only_installs_just_those_groups(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes", "--only", "sudo-docker")
        assert res.exit_code == 0, res.output
        state = load(guard_state_path(None))
        assert list(state.consents) == ["sudo-docker"] and state.agent_permissions == []
        assert not config_target(None).exists()  # nothing global to write for this group

    def test_an_unknown_group_is_a_usage_error_naming_the_valid_ones(self, stack) -> None:
        res = guard("install", "--yes", "--only", "g2,nope")
        assert res.exit_code == 2
        assert "nope" in res.output and "valid groups: g2, hooks, sudo-docker" in res.output

    def test_unavailable_groups_are_noted_and_never_recorded(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes", "--only", "repo_hooks")
        assert res.exit_code == 0
        assert "`repo_hooks`: not needed" in res.output  # git >= 2.54 on the test host
        assert not guard_state_path(None).exists() and not config_target(None).exists()

    def test_the_optional_alias_is_installed_only_by_name(self, stack) -> None:
        stack.fake()
        bare = guard("install", "--yes", "--only", "hooks,alias")
        assert bare.exit_code == 0, bare.output
        state = load(guard_state_path(None))
        assert state.consents["alias"]["decision"] == "accepted"
        got = subprocess.run(
            ["git", "config", "--file", str(carter_gitconfig_path(None)), "--get", ALIAS_KEY],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        assert got.rstrip("\n") == '!cd "${GIT_PREFIX:-.}" && carter commit'

    def test_a_user_config_is_merged_comments_are_backed_up_and_providers_survive(
        self, stack
    ) -> None:
        target = config_target(None)
        target.parent.mkdir(parents=True)
        shutil.copy(SYNTHETIC, target)
        original = target.read_bytes()
        res = install_all(stack)
        cfg = config_data()
        assert cfg["providers"]["example-gateway"] and cfg["plugins"] == ["example-plugin"]
        assert cfg["agents"]["title"] == {"model": "example-gateway/small-model"}
        assert target.with_name(target.name + ".carter-backup").read_bytes() == original
        assert "has comments" in res.output
        backup = next(backups_dir(None).glob("*/" + target.name))
        assert backup.read_bytes() == original

    def test_a_lost_provider_rolls_back(self, stack) -> None:
        stack.fake(after=debug_config(stack.live, providers={}))
        res = guard("install", "--yes")
        assert res.exit_code == 1 and E_POLICIES_MISSING in res.output
        assert not config_target(None).exists()

    def test_opencode_missing_or_broken_writes_nothing(self, stack, fake_opencode) -> None:
        fake_opencode(agents_output="boom", agents_exit=1)
        res = guard("install", "--yes")
        assert res.exit_code == 1 and "cannot list OpenCode's agents" in res.output
        assert not config_target(None).exists() and not guard_state_path(None).exists()

    def test_the_real_opencode_is_never_used(self, stack) -> None:
        res = guard("install", "--yes")  # no fake requested: the guard stub exits 97
        assert res.exit_code == 1 and not config_target(None).exists()

    def test_a_statement_of_yours_in_the_config_is_never_touched(self, stack) -> None:
        mine = {"action": "tool.use", "resource": "shell:sudo *", "effect": "deny"}
        target = config_target(None)
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"policies": [mine]}))
        install_all(stack)
        assert config_data()["policies"] == [mine]  # Carter adds and removes no policies
        assert load(guard_state_path(None)).opencode_policies == []


class TestStateGuards:
    def test_a_corrupt_state_is_quarantined_by_an_explicit_yes(self, stack) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0 and "unreadable" in res.output
        moved = list(path.parent.glob("guard-state.json.corrupt-*"))
        assert len(moved) == 1 and moved[0].read_text() == "{broken"
        assert load(path).consents

    def test_a_corrupt_state_is_moved_aside_without_a_second_question(
        self, stack, human_tty
    ) -> None:
        human_tty(True)
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        stack.fake()
        res = guard("install", input="y\n")  # the one question; moving a file aside asks nothing
        assert res.exit_code == 0 and res.output.count("Install?") == 1
        moved = list(path.parent.glob("guard-state.json.corrupt-*"))
        assert len(moved) == 1 and moved[0].read_text() == "{broken"

    def test_a_newer_schema_is_refused_and_never_rewritten(self, stack) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text('{"schema": 2}')
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 1 and E_STATE_INVALID in res.output
        assert path.read_text() == '{"schema": 2}' and not config_target(None).exists()


class TestGitStepAtomicity:
    """Carter has no git key by default, so these inject one to exercise the machinery."""

    @pytest.fixture
    def with_entry(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(gc, "carter_git_entries", STAND_IN)

    def test_the_git_step_writes_file_and_include_and_records_them(self, stack, with_entry) -> None:
        res = install_all(stack)
        carter = carter_gitconfig_path(None)
        assert carter.exists() and "include.path" not in res.output.split("git config:")[0]
        state = load(guard_state_path(None))
        assert state.gitconfig["value"] == str(carter) and state.owned_unchanged(carter)
        out = subprocess.run(
            ["git", "config", "--global", "--includes", "--get", "alias.ai-commit"],
            capture_output=True, text=True,
        )  # fmt: skip
        assert out.stdout.strip() == "!true"

    def test_a_git_failure_restores_the_config_and_keeps_the_previous_state(
        self, stack, with_entry, monkeypatch
    ) -> None:
        target = config_target(None)
        target.parent.mkdir(parents=True)
        target.write_text('{"model": "x"}\n')
        original = target.read_bytes()
        monkeypatch.setattr(gc, "apply_keys", _raises(gc.GitError("boom")))
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 1 and "boom" in res.output
        assert target.read_bytes() == original
        assert not guard_state_path(None).exists()

    def test_a_failed_new_config_file_is_removed_again(
        self, stack, with_entry, monkeypatch
    ) -> None:
        stack.fake()
        monkeypatch.setattr(gc, "add_include", _raises(gc.GitError("no")))
        res = guard("install", "--yes")
        assert res.exit_code == 1
        assert not config_target(None).exists() and not guard_state_path(None).exists()
        assert not carter_gitconfig_path(None).exists()  # created, then undone

    def test_a_failure_keeps_earlier_ownership_intact(self, stack, monkeypatch) -> None:
        install_all(stack)
        before = guard_state_path(None).read_bytes()
        monkeypatch.setattr(gc, "carter_git_entries", STAND_IN)
        monkeypatch.setattr(gc, "add_include", _raises(gc.GitError("no")))
        stack.fake(before=debug_config(stack.live))
        assert guard("install", "--yes").exit_code == 1
        assert guard_state_path(None).read_bytes() == before


class TestD52:
    def write_toml(self, home: Path, ws: Path) -> None:
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(
            f'schema = 2\n[workspaces."{ws}"]\nallow_project_opencode_edit = true\n'
        )

    def test_yes_lists_the_opt_outs_and_applies_them(
        self, stack, home: Path, tmp_path: Path
    ) -> None:
        ws = tmp_path / "proj"
        ws.mkdir()
        self.write_toml(home, ws)
        stack.fake()
        assert CliRunner().invoke(main, ["install", "--yes"], catch_exceptions=False).exit_code == 0
        agent = home / ".config" / "opencode" / "agents" / "carter-engineer.md"
        import yaml

        rules = yaml.safe_load(agent.read_text().split("---", 2)[1])["permissions"]
        allows = [
            r["resource"]
            for r in rules
            if r["action"] == "edit"
            and r["effect"] == "allow"
            and r["resource"].startswith(str(ws.resolve()))
        ]
        assert len(allows) == 3  # the opt-out is part of the Carter agents' permissions

    def test_opt_outs_come_with_the_one_question_not_a_second_one(
        self, stack, home: Path, tmp_path: Path, human_tty
    ) -> None:
        human_tty(True)
        ws = tmp_path / "proj"
        ws.mkdir()
        self.write_toml(home, ws)
        from carter.guard import optout

        extra = optout.optout_statements([str(ws.resolve())])
        stack.live = stack.live + extra
        stack.fake()
        res = guard("install", input="y\n")
        assert res.exit_code == 0, res.output
        assert res.output.count("Install?") == 1 and "Apply these opt-outs" not in res.output
        assert "Active opt-outs" in res.output and str(ws.resolve()) in res.output


class TestStatus:
    def test_absent_state_is_reported_and_nothing_is_created(self, stack) -> None:
        before = tree_hash(stack.home)
        res = guard("status")
        assert res.exit_code == 0 and "absent (nothing installed)" in res.output
        assert "Plugin: not installed" in res.output
        assert tree_hash(stack.home) == before

    def test_after_install_lists_consents_and_loaded_statements(self, stack) -> None:
        install_all(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        before = tree_hash(stack.home)
        res = guard("status")
        out = res.output
        assert res.exit_code == 0
        assert (
            "g2                 accepted" in out
            and "alias              optional, not installed" in out
        )
        assert "no global policies" in out and "MISSING" not in out
        assert "Agents with `carter_push` denied: build, explore, general, plan" in out
        assert "include.path: present in" in out and "ok      " in out
        assert tree_hash(stack.home) == before

    def test_declined_groups_are_residuals(self, stack, human_tty) -> None:
        stack.fake()
        decline("sudo-docker")
        guard("install", "--yes")
        out = guard("status").output
        assert "sudo-docker" in out and "declined" in out and "asks again" in out

    def test_a_corrupt_state_is_reported_without_writing(self, stack) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        before = tree_hash(stack.home)
        res = guard("status")
        assert res.exit_code == 0 and "CORRUPT" in res.output and "does not rebuild" in res.output
        assert tree_hash(stack.home) == before

    def test_a_newer_schema_is_reported(self, stack) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text('{"schema": 2}')
        assert "NEWER" in guard("status").output

    def test_file_drift_is_shown(self, stack, home: Path) -> None:
        install_all(stack)
        state = load(guard_state_path(None))
        f = home / ".carter" / "isolation.json"
        f.write_text("{}")
        state.record_file(f, b"{}")
        from carter.guard.state import save

        save(state, guard_state_path(None))
        stack.fake(before=debug_config(stack.live))
        assert f"ok      {f}" in guard("status").output
        f.write_text("{changed}")
        assert f"CHANGED {f}" in guard("status").output
        f.unlink()
        assert f"MISSING {f}" in guard("status").output


class TestRemove:
    def test_tears_down_policies_permissions_and_state(self, stack, human_tty) -> None:
        human_tty(True)
        install_all(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove")  # no input: it asks nothing
        assert res.exit_code == 0, res.output
        assert config_data() == {}
        assert not guard_state_path(None).exists()
        assert "Removed guard state" in res.output

    def test_the_pat_file_is_kept_with_the_exact_message_and_audit_is_kept(
        self, stack, home: Path
    ) -> None:
        install_all(stack)
        token = home / ".carter" / "secrets" / "gh-read.token"
        token.parent.mkdir(parents=True)
        token.write_text("github_pat_NOT-A-REAL-TOKEN")
        audit = home / ".carter" / "state" / "audit" / "b.jsonl"
        audit.parent.mkdir(parents=True)
        audit.write_text("{}\n")
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert PAT_MESSAGE in res.output
        assert token.read_text() == "github_pat_NOT-A-REAL-TOKEN" and audit.exists()
        assert "github_pat_NOT" not in res.output

    def test_no_pat_message_when_there_is_no_pat(self, stack) -> None:
        install_all(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config())
        assert "gh-read.token" not in guard("remove", "--yes").output

    def test_an_edited_per_agent_deny_is_kept_and_reported(self, stack) -> None:
        install_all(stack)
        cfg = config_data()
        cfg["agents"]["build"]["permissions"][0]["effect"] = "allow"
        config_target(None).write_text(json.dumps(cfg))
        stack.fake(before=debug_config(), after=debug_config())
        res = guard("remove", "--yes")
        assert "kept build:carter_push: edited since Carter wrote it" in res.output
        assert config_data()["agents"] == {
            "build": {
                "permissions": [{"action": "carter_push", "resource": "*", "effect": "allow"}]
            }
        }

    def test_removing_twice_is_a_no_op(self, stack) -> None:
        install_all(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config())
        guard("remove", "--yes")
        res = guard("remove", "--yes")
        assert res.exit_code == 0 and "Nothing to remove" in res.output

    def test_install_after_remove_restores_a_clean_state(self, stack) -> None:
        install_all(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config())
        guard("remove", "--yes")
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        assert len(load(guard_state_path(None)).agent_permissions) == 4

    def test_dry_run_writes_nothing(self, stack) -> None:
        install_all(stack)
        before = tree_hash(stack.home)
        stack.fake()
        res = guard("remove", "--dry-run")
        assert (
            res.exit_code == 0 and "dry run" in res.output and "- build:carter_push" in res.output
        )
        assert tree_hash(stack.home) == before

    def test_a_normal_run_is_one_line(self, stack, human_tty) -> None:
        human_tty(True)
        install_all(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config())
        from carter import ui

        ui.configure(verbose=False)  # install_all() above ran with -v
        res = CliRunner().invoke(main, ["guard", "remove"], catch_exceptions=False)
        assert res.exit_code == 0 and res.output == "✓ guards removed\n"

    def test_only_removes_one_group_and_its_consent(self, stack) -> None:
        install_all(stack)
        rest = policy_statements(("read-edit-denies", "config-edit", "g2"), home=str(stack.home))
        stack.fake(before=debug_config(stack.live), after=debug_config(rest))
        res = guard("remove", "--yes", "--only", "sudo-docker")
        assert res.exit_code == 0, res.output
        state = load(guard_state_path(None))
        assert "sudo-docker" not in state.consents and "g2" in state.consents
        assert "policies" not in config_data()

    def test_a_corrupt_state_is_not_removed_blindly(self, stack) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        res = guard("remove", "--yes")
        assert res.exit_code == 1 and E_STATE_INVALID in res.output and path.exists()

    def test_unrecorded_extra_files_are_kept_and_recorded_unchanged_ones_removed(
        self, stack, home: Path
    ) -> None:
        install_all(stack)
        kept = home / ".carter" / "isolation.json"
        kept.write_text("{}")  # recorded, but changed since: kept
        ours = home / ".carter" / "opencode-headless.json"
        ours.write_text("{}")
        state = load(guard_state_path(None))
        state.record_file(ours, b"{}")
        from carter.guard.state import save

        save(state, guard_state_path(None))
        stack.fake(before=debug_config(stack.live), after=debug_config())
        out = guard("remove", "--yes").output
        assert kept.exists() and not ours.exists()
        assert f"kept {kept}: changed since Carter wrote it" in out and f"removed {ours}" in out

    def test_git_config_is_undone_in_teardown_order(self, stack, monkeypatch) -> None:
        monkeypatch.setattr(gc, "carter_git_entries", STAND_IN)
        install_all(stack)
        carter = carter_gitconfig_path(None)
        global_cfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        assert str(carter) in global_cfg.read_text() and carter.exists()
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0 and not carter.exists()
        assert str(carter) not in global_cfg.read_text()

    def test_a_user_edited_carter_gitconfig_is_kept(self, stack, monkeypatch) -> None:
        monkeypatch.setattr(gc, "carter_git_entries", STAND_IN)
        install_all(stack)
        carter = carter_gitconfig_path(None)
        carter.write_text(carter.read_text() + "[user]\n\tname = mine\n")
        stack.fake(before=debug_config(stack.live), after=debug_config())
        out = guard("remove", "--yes").output
        assert carter.exists() and f"kept {carter}: edited since Carter wrote it" in out


def test_guard_help_lists_the_three_commands() -> None:
    out = CliRunner().invoke(main, ["guard", "--help"]).output
    assert all(cmd in out for cmd in ("install", "status", "remove"))
    assert "--reset-b" in CliRunner().invoke(main, ["guard", "status", "--help"]).output
