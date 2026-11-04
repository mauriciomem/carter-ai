"""``carter install`` / ``carter uninstall`` call the guard (plan 003 step 15, T16).

Install: agents and skills as before; then the guards, with the same consent rules as
``carter guard install``. A guard failure never undoes the rest and only that part exits 1.
Uninstall removes the guards first, only where unchanged, unless ``--keep-guards``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from carter.cli import main
from carter.guard import gitconfig as gc
from carter.guard.state import load
from carter.install import orchestrator, paths
from carter.install.components import read_manifest, write_manifest
from carter.install.mcp import config_target
from carter.install.paths import carter_gitconfig_path, guard_state_path, managed_roots
from guard.helpers import debug_config, tree_hash


def carter(base: Path, *args: str, input: str | None = None) -> Result:
    return CliRunner().invoke(
        main, [*args, "--base-dir", str(base)], input=input, catch_exceptions=False
    )


def cfg(base: Path) -> dict:
    return json.loads(config_target(base).read_text())


def agents_installed(base: Path) -> bool:
    return any((paths._opencode_base(base) / "agents").glob("carter-*"))


class TestInstallCallsGuard:
    def test_yes_installs_the_agents_and_then_the_guards(self, stack, base_dir: Path) -> None:
        stack.fake()
        res = carter(base_dir, "install", "--yes")
        assert res.exit_code == 0, res.output
        assert agents_installed(base_dir) and read_manifest(base_dir)
        assert "Guards (carter guard install)" in res.output
        state = load(guard_state_path(base_dir))
        assert len(state.owned_policies()) == len(stack.live)
        assert len(cfg(base_dir)["policies"]) == len(stack.live)
        assert "plugin installed:" in res.output and "restart the OpenCode server" in res.output

    def test_without_a_terminal_and_without_yes_the_guards_are_skipped_with_a_notice(
        self, stack, base_dir: Path, human_tty
    ) -> None:
        human_tty(False)
        stack.fake()
        res = carter(base_dir, "install")
        assert res.exit_code == 0, res.output
        assert agents_installed(base_dir)  # installed exactly as before
        assert "NOT installed" in res.output
        assert not guard_state_path(base_dir).exists()
        assert not config_target(base_dir).exists()

    def test_a_terminal_prompts_per_group(self, stack, base_dir: Path, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = carter(base_dir, "install", input="y\ny\nn\ny\ny\n")
        assert res.exit_code == 0, res.output
        state = load(guard_state_path(base_dir))
        assert state.consents["sudo-docker"]["decision"] == "declined"

    def test_a_guard_failure_exits_1_but_the_rest_of_the_install_stands(
        self, stack, base_dir: Path
    ) -> None:
        stack.fake(after=debug_config(stack.live[1:]))  # OpenCode drops a statement
        res = carter(base_dir, "install", "--yes")
        assert res.exit_code == 1
        assert "guards: install failed: E-POLICIES-MISSING" in res.output
        assert agents_installed(base_dir) and read_manifest(base_dir)
        assert not config_target(base_dir).exists() and not guard_state_path(base_dir).exists()
        assert "Installation complete" in res.output

    def test_an_agent_shell_never_changes_guards(
        self, stack, base_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT", "x")
        stack.fake()
        res = carter(base_dir, "install", "--yes")
        assert res.exit_code == 0 and "agent shell" in res.output
        assert agents_installed(base_dir) and not guard_state_path(base_dir).exists()

    def test_the_library_entry_point_does_not_touch_guards_by_default(
        self, base_dir: Path, fake_opencode
    ) -> None:
        fake_opencode()
        assert orchestrator.run(base_dir=base_dir, verbosity=1) == 0
        assert not guard_state_path(base_dir).exists()


class TestUpgradeKeepsGuardState:
    def test_a_second_install_keeps_state_and_config_byte_identical(
        self, stack, base_dir: Path
    ) -> None:
        stack.fake()
        assert carter(base_dir, "install", "--yes").exit_code == 0
        state_path = guard_state_path(base_dir)
        before = (state_path.read_bytes(), config_target(base_dir).read_bytes())
        os.utime(state_path, ns=(10**9, 10**9))
        stack.fake(before=debug_config(stack.live))
        assert carter(base_dir, "install", "--yes").exit_code == 0
        assert (state_path.read_bytes(), config_target(base_dir).read_bytes()) == before
        assert state_path.stat().st_mtime_ns == 10**9

    def test_an_older_installer_rebuilding_the_manifest_cannot_orphan_the_guards(
        self, stack, base_dir: Path, human_tty
    ) -> None:
        stack.fake()
        carter(base_dir, "install", "--yes")
        before = guard_state_path(base_dir).read_bytes()
        # What every pre-guard `carter install` does to manifest.json:
        write_manifest(
            {"version": "0.16.0", "files": [], "mcp_servers": [], "file_hashes": {}}, base_dir
        )
        human_tty(False)
        stack.fake(before=debug_config(stack.live))
        assert carter(base_dir, "install").exit_code == 0  # non-TTY, no --yes: skipped
        assert guard_state_path(base_dir).read_bytes() == before
        assert len(cfg(base_dir)["policies"]) == len(stack.live)


class TestUninstallRemovesGuards:
    def installed(self, stack, base_dir: Path) -> None:
        stack.fake()
        assert carter(base_dir, "install", "--yes").exit_code == 0

    def finish(self, stack) -> None:
        stack.fake(before=debug_config(stack.live), after=debug_config())

    def test_yes_removes_guards_then_the_install(self, stack, base_dir: Path) -> None:
        self.installed(stack, base_dir)
        self.finish(stack)
        res = carter(base_dir, "uninstall", "--yes")
        assert res.exit_code == 0, res.output
        assert cfg(base_dir) == {}
        assert not guard_state_path(base_dir).exists() and not agents_installed(base_dir)
        assert res.output.index("Removed guard state") < res.output.index("Uninstall complete")

    def test_keep_guards_leaves_policies_permissions_and_state(self, stack, base_dir: Path) -> None:
        self.installed(stack, base_dir)
        before = (guard_state_path(base_dir).read_bytes(), config_target(base_dir).read_bytes())
        res = carter(base_dir, "uninstall", "--keep-guards", "--yes")
        assert res.exit_code == 0
        assert (
            guard_state_path(base_dir).read_bytes(),
            config_target(base_dir).read_bytes(),
        ) == before
        assert not agents_installed(base_dir)

    def test_without_a_terminal_and_without_yes_the_guards_are_kept(
        self, stack, base_dir: Path, human_tty
    ) -> None:
        self.installed(stack, base_dir)
        human_tty(False)
        before = guard_state_path(base_dir).read_bytes()
        res = carter(base_dir, "uninstall")
        assert res.exit_code == 0 and "kept: no terminal and no --yes" in res.output
        assert guard_state_path(base_dir).read_bytes() == before and not agents_installed(base_dir)

    def test_an_agent_shell_cannot_remove_guards(
        self, stack, base_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.installed(stack, base_dir)
        monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_1")
        res = carter(base_dir, "uninstall", "--yes")
        assert res.exit_code == 0 and "kept: agent shell" in res.output
        assert guard_state_path(base_dir).exists()

    def test_edited_items_are_kept_and_reported_unedited_ones_removed(
        self, stack, base_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gc, "carter_git_entries", lambda *_a, **_k: [("carter.tier", "t1")])
        self.installed(stack, base_dir)
        data = cfg(base_dir)
        data["policies"][0]["resource"] = "shell:git push --edited *"  # a Carter policy tuple
        data["agents"]["build"]["permissions"][0]["effect"] = "allow"  # a permission value
        config_target(base_dir).write_text(json.dumps(data))
        carter_file = carter_gitconfig_path(base_dir)
        carter_file.write_text(carter_file.read_text() + "[user]\n\tname = mine\n")  # the gitconfig
        self.finish(stack)
        res = carter(base_dir, "uninstall", "--yes")
        assert res.exit_code == 0, res.output
        out = res.output
        assert "kept deny-git-push: edited since Carter wrote it" in out
        assert "kept build:carter_push: edited since Carter wrote it" in out
        assert f"kept {carter_file}: edited since Carter wrote it" in out
        left = cfg(base_dir)
        assert [p["resource"] for p in left["policies"]] == ["shell:git push --edited *"]
        assert left["agents"]["build"]["permissions"] == [
            {"action": "carter_push", "resource": "*", "effect": "allow"}
        ]
        assert carter_file.exists()
        assert str(carter_file) not in Path(os.environ["GIT_CONFIG_GLOBAL"]).read_text()

    def test_preexisting_user_entries_are_never_touched(self, stack, base_dir: Path) -> None:
        mine = {"action": "tool.use", "resource": "shell:sudo *", "effect": "deny"}
        rule = {"action": "carter_pr", "resource": "*", "effect": "deny"}
        target = config_target(base_dir)
        target.parent.mkdir(parents=True)
        target.write_text(
            json.dumps({"policies": [mine], "agents": {"plan": {"permissions": [rule]}}})
        )
        self.installed(stack, base_dir)
        self.finish(stack)
        assert carter(base_dir, "uninstall", "--yes").exit_code == 0
        left = cfg(base_dir)
        assert left["policies"] == [mine]
        assert left["agents"]["plan"]["permissions"] == [rule]

    def test_a_guard_failure_exits_1_but_the_rest_is_removed(
        self, stack, base_dir: Path, fake_opencode
    ) -> None:
        self.installed(stack, base_dir)
        fake_opencode(config_output="boom", config_exit=1)  # cannot verify: nothing is written
        res = carter(base_dir, "uninstall", "--yes")
        assert res.exit_code == 1 and "guards: removal failed" in res.output
        assert not agents_installed(base_dir) and "Uninstall complete" in res.output
        assert guard_state_path(base_dir).exists()  # still owned, so a later remove can finish

    def test_without_guard_state_or_manifest_nothing_outside_carters_roots_is_removed(
        self, base_dir: Path
    ) -> None:
        carter_dir = base_dir / "carter"
        for rel in (
            "memories/user/n.md",
            "config.toml",
            "state/audit/b.jsonl",
            "binary/x",
            "hooks-old/y",
        ):
            f = carter_dir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("mine")
        before = tree_hash(base_dir)
        res = carter(base_dir, "uninstall", "--yes")
        assert res.exit_code == 0 and "Nothing to remove" not in res.output
        assert tree_hash(base_dir) == before

    def test_no_guard_chatter_when_carter_owns_no_guards(
        self, base_dir: Path, fake_opencode
    ) -> None:
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        res = carter(base_dir, "uninstall")
        assert "Removing guards" not in res.output and "guards:" not in res.output


class TestManagedRoots:
    def test_bin_hooks_run_are_managed_by_path(self, base_dir: Path) -> None:
        roots = managed_roots(base_dir)
        carter_dir = (base_dir / "carter").resolve()
        assert {carter_dir / "bin", carter_dir / "hooks", carter_dir / "run"} <= set(roots)
        assert paths._opencode_base(base_dir).resolve() in roots

    def test_containment_is_by_path_component_not_string_prefix(self, base_dir: Path) -> None:
        from carter.install.ownership import _within

        roots = managed_roots(base_dir)
        carter_dir = (base_dir / "carter").resolve()
        assert _within(carter_dir / "bin" / "carter-guard", roots)
        assert not _within(carter_dir / "binary" / "x", roots)
        assert not _within(carter_dir / "hooks-old" / "y", roots)
        assert not _within(carter_dir / "memories" / "n.md", roots)
        assert not _within(carter_dir / "config.toml", roots)


class TestRoundTrip:
    def test_install_status_remove_restores_the_tree_but_for_backups_and_json_formatting(
        self, stack, home: Path
    ) -> None:
        user = home / ".config" / "opencode" / "opencode.json"
        user.parent.mkdir(parents=True)
        user.write_text('{"model": "x"}\n')
        (home / ".carter").mkdir()
        (home / ".carter" / "config.toml").write_text("schema = 2\n")
        before = tree_hash(home)
        stack.fake()
        runner = CliRunner()
        assert (
            runner.invoke(main, ["guard", "install", "--yes"], catch_exceptions=False).exit_code
            == 0
        )
        stack.fake(before=debug_config(stack.live))
        assert runner.invoke(main, ["guard", "status"], catch_exceptions=False).exit_code == 0
        stack.fake(before=debug_config(stack.live), after=debug_config())
        assert (
            runner.invoke(main, ["guard", "remove", "--yes"], catch_exceptions=False).exit_code == 0
        )
        after = tree_hash(home, skip=("backups",))
        # The user's JSON is rewritten (formatting normalised) but means the same thing.
        key = ".config/opencode/opencode.json"
        assert {k: v for k, v in after.items() if k != key} == {
            k: v for k, v in before.items() if k != key
        }
        assert json.loads(user.read_text()) == {"model": "x"}
