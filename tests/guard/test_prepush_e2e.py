"""``pre-push`` end to end: real git, a ``file://`` bare remote, the sandbox HOME
(plan 004 step 23; RFC-0007 §5 2a, §9).

The hook is installed the way ``carter guard install`` does it (step 24): ``carter-guard`` in
``~/.carter/hooks``, ``hook.carter-guard-pre-push.*`` in ``~/.carter/gitconfig`` and one include
line in the (sandbox) global config. It is the backstop when the OpenCode plugin is not loaded,
so no plugin, no isolation block and no gate exist in these tests. Needs git >= 2.54.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from carter.guard import gitconfig, hooks
from carter.guard.state import GuardState
from carter.identity.errors import registry
from carter.install.paths import carter_gitconfig_path, guard_script_path

AGENT_ENVS = [
    pytest.param({"AGENT": "1"}, id="AGENT"),
    pytest.param({"OPENCODE_SESSION_ID": "ses_e2e"}, id="OPENCODE_SESSION_ID"),
    pytest.param({"CARTER_AGENT_SHELL": "1"}, id="CARTER_AGENT_SHELL"),
]
SIGNALS = ("AGENT", "AI_AGENT", "OPENCODE", "OPENCODE_SESSION_ID", "CARTER_AGENT_SHELL")


def _git_version() -> tuple[int, ...]:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


pytestmark = pytest.mark.skipif(
    _git_version() < (2, 54), reason="config-based hooks need git >= 2.54 (old git: step 25)"
)


def git(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=60,
    )


class Rig:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.remote = root / "remote.git"
        self.work = root / "work"
        assert git("init", "-q", "--bare", "-b", "main", str(self.remote)).returncode == 0
        assert git("init", "-q", "-b", "main", str(self.work)).returncode == 0
        git("remote", "add", "origin", f"file://{self.remote}", cwd=self.work)
        self.commit("seed")

    def commit(self, name: str) -> None:
        (self.work / name).write_text(name)
        git("add", name, cwd=self.work)
        done = git("commit", "-q", "-m", name, cwd=self.work)
        assert done.returncode == 0, done.stderr

    def remote_head(self) -> str:
        done = git("rev-parse", "--verify", "-q", "refs/heads/main", cwd=self.remote)
        return done.stdout.strip() if done.returncode == 0 else ""

    def push(self, env: dict[str, str] | None = None, *flags: str, pre: tuple[str, ...] = ()):
        return git(*pre, "push", *flags, "origin", "main", cwd=self.work, env=env)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def install_hook() -> Path:
    """What step 24's install writes, via the production functions (sandbox HOME)."""
    state = GuardState()
    hooks.install_script(None, state)
    script = guard_script_path(None)
    res = gitconfig.apply_keys(
        hooks.hook_entries(script), mode="include", base_dir=None, state=state
    )
    assert res.include is not None and res.include.status == "added"
    return script


@pytest.fixture
def hooked(rig: Rig) -> Rig:
    install_hook()
    return rig


class TestTheHookIsSeenAsGlobal:
    def test_git_lists_it_with_scope_global(self, hooked: Rig) -> None:
        done = git("hook", "list", "--show-scope", "pre-push", cwd=hooked.work)
        assert done.stdout.split() == ["global", "carter-guard-pre-push"]


class TestAgentVersusHuman:
    @pytest.mark.parametrize("env", AGENT_ENVS)
    def test_an_agent_push_is_blocked_and_the_remote_is_unchanged(
        self, env: dict[str, str], hooked: Rig
    ) -> None:
        hooked.commit("agent-work")
        done = hooked.push(env)
        assert done.returncode != 0
        assert registry()["E-PUSH-GUARD"].message.split("<reason>")[0] in done.stderr
        assert "carter push" in done.stderr
        assert hooked.remote_head() == ""  # nothing ever reached the remote

    def test_the_same_push_from_a_human_env_succeeds(self, hooked: Rig) -> None:
        hooked.commit("human-work")
        done = hooked.push()
        assert done.returncode == 0, done.stderr
        head = git("rev-parse", "HEAD", cwd=hooked.work).stdout.strip()
        assert hooked.remote_head() == head

    def test_a_blocked_agent_push_then_a_human_push_of_the_same_commit(self, hooked: Rig) -> None:
        assert hooked.push({"AGENT": "1"}).returncode != 0
        assert hooked.push().returncode == 0

    def test_scrubbed_is_human_the_documented_ad1_limit(self, hooked: Rig) -> None:
        """An agent that adds ``CARTER_HUMAN_SHELL`` looks like a human to AD1 (RFC App C.1).
        The gate and the isolation block are what stop that route; the hook cannot."""
        env = {"AGENT": "1", "CARTER_HUMAN_SHELL": "1"}
        assert hooked.push(env).returncode == 0

    def test_the_strong_marker_beats_the_human_tag(self, hooked: Rig) -> None:
        env = {"CARTER_AGENT_SHELL": "1", "CARTER_HUMAN_SHELL": "1"}
        assert hooked.push(env).returncode != 0
        assert hooked.remote_head() == ""


class TestUrlForms:
    @pytest.mark.parametrize(
        "url",
        [
            "git@github.com:o/r.git",
            "ssh://git@github.com/o/r.git",
            "https://github.com/o/r.git",
        ],
    )
    def test_the_hook_fires_for_each_github_form_before_any_transport(
        self, url: str, hooked: Rig
    ) -> None:
        git("config", "--global", f"url.file://{hooked.remote}.insteadOf", url)
        git("remote", "set-url", "origin", url, cwd=hooked.work)
        assert hooked.push({"AGENT": "1"}).returncode != 0
        assert hooked.remote_head() == ""
        human = hooked.push()
        assert human.returncode == 0, human.stderr
        assert hooked.remote_head() != ""


class TestSurvival:
    def test_blocked_also_with_core_hookspath_dev_null(self, hooked: Rig) -> None:
        done = hooked.push({"AGENT": "1"}, pre=("-c", "core.hooksPath=/dev/null"))
        assert done.returncode != 0 and hooked.remote_head() == ""

    def test_no_verify_skips_the_hook_a_documented_limit(self, hooked: Rig) -> None:
        """``git push --no-verify`` skips every pre-push hook, config hooks included (spike E 5).
        With the plugin loaded the gate rejects every ``git push``; the hook is the backstop only
        for pushes the gate never saw."""
        done = hooked.push({"AGENT": "1"}, "--no-verify")
        assert done.returncode == 0, done.stderr
        assert hooked.remote_head() != ""

    def test_an_edited_environment_cannot_switch_the_hook_off_without_the_gate_rules(
        self, hooked: Rig
    ) -> None:
        """``-c hook.<name>.enabled=false`` works in git; the gate refuses ``-c hook.*`` (corpus
        ``x-c-hooks-enabled``). This pins why that gate rule is load-bearing."""
        off = ("-c", "hook.carter-guard-pre-push.enabled=false")
        assert hooked.push({"AGENT": "1"}, pre=off).returncode == 0


class TestCoexistence:
    def test_a_repo_hook_and_the_config_hook_both_run(self, hooked: Rig, tmp_path: Path) -> None:
        marker = tmp_path / "repo-hook-ran"
        hook = hooked.work / ".git" / "hooks" / "pre-push"
        hook.write_text(f"#!/bin/sh\necho ran >> {marker}\nexit 0\n")
        hook.chmod(0o755)
        assert hooked.push().returncode == 0 and marker.read_text() == "ran\n"
        marker.unlink()
        assert hooked.push({"AGENT": "1"}).returncode != 0

    def test_a_husky_style_hookspath_and_the_config_hook_both_run(
        self, hooked: Rig, tmp_path: Path
    ) -> None:
        husky = hooked.work / ".husky" / "_"
        husky.mkdir(parents=True)
        marker = tmp_path / "husky-ran"
        (husky / "pre-push").write_text(f"#!/bin/sh\necho ran >> {marker}\nexit 0\n")
        (husky / "pre-push").chmod(0o755)
        git("config", "core.hooksPath", str(husky), cwd=hooked.work)
        assert hooked.push().returncode == 0 and marker.read_text() == "ran\n"
        assert hooked.push({"AGENT": "1"}).returncode != 0

    def test_a_failing_repo_hook_still_blocks_a_human_push(
        self, hooked: Rig
    ) -> None:  # the repo's own policy is theirs
        hook = hooked.work / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        assert hooked.push().returncode != 0


class TestWhenCarterIsDamaged:
    def test_a_deleted_script_blocks_only_the_agent(self, hooked: Rig) -> None:
        guard_script_path(None).unlink()
        assert hooked.push({"AGENT": "1"}).returncode != 0
        assert hooked.remote_head() == ""
        assert hooked.push().returncode == 0

    def test_a_deleted_gitconfig_blocks_nobody_and_never_breaks_git(self, hooked: Rig) -> None:
        """Without the hook entries there is nothing to run (the plugin and gate are the layer)."""
        carter_gitconfig_path(None).unlink()
        assert git("status", cwd=hooked.work).returncode == 0
        assert hooked.push().returncode == 0


class TestPluginNotLoaded:
    def test_no_plugin_no_isolation_agent_push_is_blocked_and_names_carter_push(
        self, hooked: Rig
    ) -> None:
        assert not (Path.home() / ".carter" / "isolation.json").exists()
        assert not (Path.home() / ".config" / "opencode" / "plugins").exists()
        done = hooked.push({"OPENCODE_SESSION_ID": "ses_x"})
        assert done.returncode != 0
        assert "`carter push`" in done.stderr
        assert hooked.remote_head() == ""


def test_the_agent_signals_used_here_are_the_data_files() -> None:
    from carter.identity.rules import load_rules

    assert set(SIGNALS) == set(load_rules().agent_signals)
