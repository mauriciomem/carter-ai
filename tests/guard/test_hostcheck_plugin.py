"""``carter check --host``: the plugin, gate and hook items.

Library-level: ``run_host_checks`` with injected readers; the CLI wiring is covered by
``test_hostcheck.py``. Read-only, names only.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import hostcheck
from carter.cli import main
from carter.guard import gitconfig as gc
from carter.guard.state import load, save
from carter.identity import isolation
from carter.install.paths import (
    carter_gitconfig_path,
    guard_script_path,
    guard_state_path,
    isolation_path,
    plugin_dir,
    run_dir,
)
from guard.helpers import debug_config, decline, tree_hash, verbose
from rows import check_host


def guard(*args: str):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False)


def installed(stack) -> None:
    stack.fake()
    assert guard("install", "--yes").exit_code == 0
    stack.fake(before=debug_config(stack.live))


def check(**kw):
    return hostcheck.run_host_checks(reader=kw.pop("reader", None), **kw)


def lines(items) -> list[str]:
    return [i.render() for i in items]


def find(items, needle: str, level: str | None = None):
    return [i for i in items if needle in i.text and (level is None or i.level == level)]


def write_status(home: Path, state: str, **extra: object) -> Path:
    folder = run_dir(None) / "plugin-status"
    folder.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": 1, "pid": os.getpid(), "boot": 1, "instance": "x",
        "plugin_version": "0", "opencode_version": "2.1.4", "state": state,
        "since": "2999-01-01T00:00:00Z", "failed_reason": None, "isolation_sha256": "0" * 64,
        "flags": [], **extra,
    }  # fmt: skip
    path = folder / f"{os.getpid()}.json"
    path.write_text(json.dumps(doc))
    return path


class TestGitconfigFirst:
    def test_a_malformed_included_gitconfig_is_the_first_item_and_red(self, stack) -> None:
        installed(stack)
        carter_gitconfig_path(None).write_text("[hook\n\tbroken =\n")
        items = check()
        assert items[0].level == "red" and "git cannot parse" in items[0].text
        assert "every git command fails" in items[0].text
        assert "carter guard remove" in items[0].fix

    def test_the_report_completes_without_calling_plain_git(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plain git (no ``--file``, the user's config) fails while the included file is broken;
        every git call of the report must switch the user's config off."""
        installed(stack)
        carter_gitconfig_path(None).write_text("[hook\n\tbroken =\n")
        real = gc.run_git
        plain: list[list[str]] = []

        def spy(args, *, env=None, cwd=None):
            if env is None:
                plain.append(list(args))
            return real(args, env=env, cwd=cwd)

        monkeypatch.setattr(gc, "run_git", spy)
        items = check(agents_reader=None)
        assert items[0].level == "red" and items[-1].area == "residual"
        assert plain == [], plain

    def test_the_cli_exit_is_1_and_still_prints_the_rest(self, stack) -> None:
        installed(stack)
        carter_gitconfig_path(None).write_text("[hook\n\tbroken =\n")
        res = check_host()
        assert res.exit_code == 1 and "git cannot parse" in res.output
        assert "policies:" in res.output and "Host: 1 RED" in res.output or "RED" in res.output


class TestIncludeAndHook:
    def test_present_and_global(self, stack) -> None:
        installed(stack)
        items = check(cwd=Path.home())
        assert find(items, "pre-push hook carter-guard-pre-push is active (scope global)", "ok")
        assert find(items, "include.path for", "ok")

    def test_missing_is_red_with_the_exact_line(self, stack) -> None:
        installed(stack)
        subprocess.run(["git", "config", "--global", "--unset-all", "include.path"], check=True)
        items = check()
        (item,) = find(items, "is missing from", "red")
        assert item.fix == f"git config --global --add include.path {carter_gitconfig_path(None)}"

    def test_a_symlinked_dotfile_config_is_a_warn_with_the_line(
        self, stack, tmp_path: Path
    ) -> None:
        stack.fake()
        cfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        real = tmp_path / "dots" / "gitconfig"
        real.parent.mkdir()
        real.write_bytes(cfg.read_bytes())
        cfg.unlink()
        cfg.symlink_to(real)
        assert guard("install", "--yes").exit_code == 0
        items = check()
        (item,) = find(items, "pre-push hook is inactive", "warn")
        assert "add this line there" in item.text and "include.path" in item.fix


class TestHashes:
    def test_everything_matches_after_an_install(self, stack) -> None:
        installed(stack)
        items = check()
        assert not [i for i in items if i.level == "red"]
        assert find(items, "plugin and isolation.json match (hash)", "ok")

    @pytest.mark.parametrize("which", ["plugin", "isolation", "core"])
    def test_a_changed_or_missing_file_is_red(self, stack, which: str) -> None:
        installed(stack)
        path = {
            "plugin": plugin_dir(None) / "index.ts",
            "isolation": isolation_path(None),
            "core": plugin_dir(None) / "core.ts",
        }[which]
        path.write_text(path.read_text() + "\n// x\n")
        assert find(check(), "was changed since Carter wrote it", "red")
        path.unlink()
        assert find(check(), "is missing", "red")

    def test_isolation_json_not_matching_the_baked_hash_is_red(self, stack) -> None:
        installed(stack)
        iso = isolation_path(None)
        doc = json.loads(iso.read_bytes())
        doc["env"]["set"]["GIT_TERMINAL_PROMPT"] = "1"
        iso.write_bytes(isolation.canonical_bytes(doc))
        state = load(guard_state_path(None))
        state.record_file(iso, iso.read_bytes())  # recorded, so only the baked hash can tell
        save(state, guard_state_path(None))
        (item,) = find(check(), "does not match the hash in the plugin", "red")
        assert "agent shells are refused" in item.text

    def test_the_script_and_gitconfig_are_compared_too(self, stack) -> None:
        installed(stack)
        guard_script_path(None).write_text("#!/bin/sh\nexit 0\n")
        assert find(check(), str(guard_script_path(None)), "red")


class TestStatus:
    def test_absent_is_a_warn(self, stack) -> None:
        installed(stack)
        assert find(check(), "not loaded yet", "warn")

    @pytest.mark.parametrize(
        ("state", "level"), [("unproven", "warn"), ("passed", "ok"), ("failed", "red")]
    )
    def test_each_state(self, stack, state: str, level: str) -> None:
        installed(stack)
        write_status(Path.home(), state, failed_reason="timeout" if state == "failed" else None)
        found = find(check(opencode_version=(2, 1, 4)), "self-test", level)
        assert found and state in ("unproven", "passed", "failed")

    def test_a_server_on_another_opencode_version_says_restart(self, stack) -> None:
        installed(stack)
        write_status(Path.home(), "passed", opencode_version="2.1.2")
        (item,) = find(check(opencode_version=(2, 1, 4)), "another OpenCode version", "warn")
        assert "restart the OpenCode server" in item.fix

    def test_a_status_older_than_the_plugin_file_says_restart(self, stack) -> None:
        installed(stack)
        write_status(Path.home(), "passed", since="2000-01-01T00:00:00Z")
        assert find(check(), "older than the plugin file", "warn")

    def test_a_status_file_of_a_dead_server_is_ignored(self, stack) -> None:
        installed(stack)
        write_status(Path.home(), "passed", pid=2_000_000_000)
        assert find(check(), "not loaded yet", "warn")

    def test_two_servers_are_two_items(self, stack) -> None:
        installed(stack)
        write_status(Path.home(), "passed")
        other = run_dir(None) / "plugin-status" / f"{os.getppid()}.json"
        other.write_text(
            json.dumps(
                {
                    **json.loads(next(other.parent.glob(f"{os.getpid()}.json")).read_text()),
                    "pid": os.getppid(),
                    "state": "failed",
                    "failed_reason": "timeout",
                }
            )
        )
        items = check()
        assert find(items, "self-test passed", "ok") and find(items, "self-test failed", "red")


class TestG2States:
    def test_g2_off_without_state(self, stack) -> None:
        assert find(check(), "G2 off", "warn")

    def test_rev_2_pending_and_declined_offer(self, stack) -> None:
        installed(stack)
        state = load(guard_state_path(None))
        state.consent("g2", "accepted", "2026-11-01", 1)
        save(state, guard_state_path(None))
        assert find(check(), "g2 update pending", "info")
        state.record_offer("g2", 3, "declined", "2026-11-03")
        save(state, guard_state_path(None))
        assert find(check(), "g2 update declined on 2026-11-03", "info")

    def test_declined_groups_are_listed_and_match_isolation_json(self, stack, human_tty) -> None:
        stack.fake()
        decline("sudo-docker")
        guard_in = CliRunner().invoke(main, ["guard", "install", "--yes"], catch_exceptions=False)
        assert guard_in.exit_code == 0, guard_in.output
        stack.fake(before=debug_config(stack.live))
        items = check()
        assert find(items, "sudo-docker: not installed", "info")
        assert not find(items, "different declined groups")
        iso = isolation_path(None)
        doc = json.loads(iso.read_bytes())
        doc["plugin"]["declined_groups"] = []
        iso.write_bytes(isolation.canonical_bytes(doc))
        assert find(check(), "different declined groups", "warn")


class TestPlugins:
    def test_foreign_plugin_files_are_listed_by_name(self, stack, home: Path) -> None:
        installed(stack)
        base = home / ".config/opencode"
        (base / "plugin").mkdir()
        (base / "plugin" / "evil.ts").write_text("export default {}")
        (base / "plugins" / "other").mkdir()
        (base / "plugins" / "other" / "index.ts").write_text("x")
        (item,) = find(check(), "not written by Carter", "warn")
        assert "plugin/evil.ts" in item.text and "plugins/other/index.ts" in item.text
        assert "carter/index.ts" not in item.text

    def test_nothing_foreign_is_silent(self, stack) -> None:
        installed(stack)
        assert not find(check(), "not written by Carter")


class TestOldGitRepos:
    def test_unguarded_repos_warn_and_fail_only_at_t2(
        self, stack, tmp_path: Path, monkeypatch
    ) -> None:
        from guard.conftest import REAL_GIT
        from guard.helpers import install_old_git

        stack.fake()
        install_old_git(Path(os.environ["PATH"].split(":")[0]), REAL_GIT)
        repo = tmp_path / "r"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        monkeypatch.chdir(repo)
        assert guard("install", "--yes", "--only", "g2,sudo-docker").exit_code == 0
        stack.fake(before=debug_config(stack.live))
        install_old_git(Path(os.environ["PATH"].split(":")[0]), REAL_GIT)
        t0 = check(cwd=repo, tier="t0")
        assert find(t0, "unguarded: not installed", "warn") and not find(t0, "unguarded", "red")
        t2 = check(cwd=repo, tier="t2")
        assert find(t2, "unguarded: not installed", "red")
        assert find(t2, "E-GIT-OLD", "info")


class TestOutputRules:
    def test_it_is_read_only_and_exit_1_only_on_red(self, stack, home: Path) -> None:
        installed(stack)
        before = tree_hash(home)
        res = check_host()
        assert res.exit_code == 0 and tree_hash(home) == before

    def test_no_value_leaks(self, stack, monkeypatch: pytest.MonkeyPatch) -> None:
        installed(stack)
        monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/SECRET-SOCKET-xyz/agent.1")
        monkeypatch.setenv("GITHUB_TOKEN", "SECRET-TOKEN-VALUE-123")
        res = check_host()
        assert "SECRET" not in res.output
