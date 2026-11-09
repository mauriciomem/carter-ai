"""`carter save` works in an agent shell while the commit guards are installed.

Carter's own state commits (the `.carter/` recovery repo) scrub `GIT_COMMITTER_*` and
`CARTER_IDENTITY*` on purpose: they are the human's, unsigned, whatever the environment. In an agent
shell the guard hook still saw `CARTER_AGENT_SHELL=1` with no identity block and rejected the commit
("agent commits need the Carter identity block"). The state commit now runs without the agent
signals, so the guard treats it as the human's own commit; every other repo is judged as before.

Real git, the real guard script as a hook, an agent shell with LLM signing on.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from carter import gate
from carter.identity.errors import registry
from carter.identity.scrub import scrub_git_env
from carter.state import commit_state
from guard.test_carter_guard_commit_events import AGENT, World


def git(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, env=env or dict(os.environ), capture_output=True, text=True
    )


@pytest.fixture
def state_world(tmp_path: Path) -> World:
    """A `.carter` state repo with the commit hooks installed, LLM signing on."""
    repo = tmp_path / "ws" / ".carter"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Hu Man")
    git(repo, "config", "user.email", "human@example.invalid")
    world = World(Path(os.environ["HOME"]), repo)
    world.configure("t2")
    world.install_repo_hooks()
    return world


@pytest.fixture
def agent_shell(state_world: World, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The process environment of an agent shell: the plugin's tag and identity block."""
    env = state_world.env()
    assert env["CARTER_AGENT_SHELL"] == "1" and "CARTER_IDENTITY" in env
    for key in [k for k in os.environ if k not in env]:
        monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


class TestTheBugIsReal:
    def test_a_scrubbed_agent_environment_is_rejected_by_the_guard(
        self, state_world: World, agent_shell: dict[str, str]
    ) -> None:
        """What `_run_git` used to send: the block is gone, the agent tag is not."""
        (state_world.repo / "plan.md").write_text("x\n")
        git(state_world.repo, "add", "-A")
        done = git(state_world.repo, "commit", "-m", "x", env=scrub_git_env(agent_shell))
        assert done.returncode != 0
        assert registry()["E-GUARD-NOIDENT"].message in done.stderr


class TestCarterSave:
    def test_the_state_commit_works_in_an_agent_shell(
        self, state_world: World, agent_shell: dict[str, str]
    ) -> None:
        (state_world.repo / "plan.md").write_text("x\n")
        assert commit_state(state_world.repo, "chore: snapshot") is True
        fmt = "%an <%ae>|%cn <%ce>|%G?"
        shown = git(state_world.repo, "log", "-1", f"--format={fmt}").stdout.strip()
        human = "Hu Man <human@example.invalid>"
        assert shown == f"{human}|{human}|N"  # human author, human committer, unsigned
        body = git(state_world.repo, "log", "-1", "--format=%B").stdout
        assert "Assisted-by: Carter" in body or "Co-authored-by:" in body

    def test_an_empty_snapshot_and_a_second_one_work_too(
        self, state_world: World, agent_shell: dict[str, str]
    ) -> None:
        assert commit_state(state_world.repo, "chore: init", allow_empty=True) is True
        (state_world.repo / "a.md").write_text("1\n")
        assert commit_state(state_world.repo, "chore: one") is True
        assert commit_state(state_world.repo, "chore: nothing to save") is False


class TestNothingElseIsLoosened:
    def test_an_ordinary_repo_is_still_judged_as_an_agent_shell(
        self, tmp_path: Path, state_world: World, agent_shell: dict[str, str]
    ) -> None:
        """The agent tag is dropped only for Carter's own call: the same hook still rejects an
        agent commit that lacks the identity block, in any other repository."""
        repo = tmp_path / "other"
        repo.mkdir()
        git(repo, "init", "-q")
        other = World(state_world.home, repo)
        other.install_repo_hooks()
        (repo / "f.txt").write_text("x\n")
        git(repo, "add", "-A")
        no_block = {k: v for k, v in agent_shell.items() if not k.startswith("CARTER_IDENTITY")}
        done = git(repo, "commit", "-m", "x", env={**scrub_git_env(no_block), **AGENT})
        assert done.returncode != 0 and registry()["E-GUARD-NOIDENT"].message in done.stderr

    @pytest.mark.parametrize(
        "command",
        [
            "git -c hook.carter-guard-prepare-commit-msg.enabled=false commit -m x",
            "git -c core.hooksPath=/dev/null commit -m x",
            "git commit --no-verify -m x",
        ],
    )
    def test_an_agent_cannot_switch_the_hooks_off_itself(self, command: str) -> None:
        assert gate.check(command).decision == "deny"
