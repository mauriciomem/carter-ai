"""D71 on a real OpenCode: G2 applies only to Carter agents (global install) and Carter workspaces.

The REAL plugin, gate, hooks and Python, an isolated HOME, the mock model. A shell of another agent
(``build``) is untouched: no isolation, no gate, no tag, and its ``git push`` is not stopped by
Carter's hook. A Carter agent and its generic subagent are covered. In a Carter workspace every
agent is covered, and a shell outside the workspace is not. Opt-in: ``CARTER_E2E=1``; runs on the
primary binary and ``CARTER_E2E_OPENCODE_ALT`` (2.1.2).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from e2e.g2 import CARTER, NAMES, SERVER_ENV, bang, error_message, make, run_shell, wait_status
from e2e.harness import CARTER_E2E_AGENT_MD, Rig

pytestmark = pytest.mark.e2e

REFUSED = "Refused by the Carter command gate (rule `"
ISOLATION = {"CARTER_AGENT_SHELL", "GH_TOKEN", "GIT_CONFIG_COUNT", "GIT_SSH_COMMAND"}
TAGS = {"CARTER_AGENT_SHELL", "CARTER_HUMAN_SHELL"}


def installed(rig_factory, opencode_bin, **kw) -> Rig:
    """A rig with the guards installed the user's way (``guard install --yes``) and restarted."""
    rig = make(rig_factory, opencode_bin, files={}, **kw)
    done = rig.run([*CARTER, "guard", "install", "--yes"], timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr
    rig.restart()
    return rig


def force_shell(rig: Rig, command: str, *, agent: str, workdir: Path | None = None) -> str:
    """A shell tool call with an explicit ``workdir``, as the named agent; the raw tool result."""
    args = {"command": command, "description": "e2e"}
    if workdir is not None:
        args["workdir"] = str(workdir)
    sid = rig.new_session(agent)
    seen = len(rig.results())
    rig.prompt(sid, f"FORCE shell {json.dumps(args)}")
    return str(rig.wait_results(seen + 1, timeout=40)[-1]["result"])


def names_of(raw: str) -> set[str]:
    return set(raw.split())


def add_origin(rig: Rig) -> Path:
    """A bare repository as ``origin`` of the workspace, so a push can actually succeed."""
    remote = rig.base / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "-C", str(rig.ws), "remote", "add", "origin", str(remote)], check=True)
    return remote


class TestGlobalInstallScope:
    def test_another_agents_shell_is_untouched(self, rig_factory, opencode_bin) -> None:
        rig = installed(rig_factory, opencode_bin, env={})
        theirs = names_of(run_shell(rig, NAMES, agent="build"))
        assert {"SSH_AUTH_SOCK", "GITHUB_TOKEN"} <= theirs, theirs  # nothing was scrubbed
        assert not theirs & (ISOLATION | TAGS), theirs  # no isolation block and no tag at all
        witness = rig.ws / "ran"
        out = run_shell(rig, f"git -C . push; touch {witness}", agent="build")
        assert not error_message(out).startswith(REFUSED) and witness.exists()  # no gate

    def test_a_carter_agent_and_its_generic_subagent_are_covered(
        self, rig_factory, opencode_bin
    ) -> None:
        rig = installed(rig_factory, opencode_bin, env={})
        mine = names_of(run_shell(rig, NAMES))  # the rig's Carter agent
        assert mine >= ISOLATION and not mine & {"SSH_AUTH_SOCK", "GITHUB_TOKEN"}, mine
        seen = len(rig.results())
        sid = rig.new_session()
        rig.prompt(sid, f"TASK RUN {NAMES}")  # the task tool starts `general` in a child session
        child = names_of(str(rig.wait_results(seen + 2)[seen]["result"]))  # the child's own shell
        assert "CARTER_AGENT_SHELL" in child and "SSH_AUTH_SOCK" not in child, child
        witness = rig.ws / "ran"
        refused = error_message(run_shell(rig, f"git -C . push; touch {witness}"))
        assert refused.startswith(REFUSED) and not witness.exists()

    def test_the_subagent_of_another_agent_stays_untouched(self, rig_factory, opencode_bin) -> None:
        rig = installed(rig_factory, opencode_bin, env={})
        seen = len(rig.results())
        sid = rig.new_session("build")
        rig.prompt(sid, f"TASK RUN {NAMES}")
        child = names_of(str(rig.wait_results(seen + 2)[seen]["result"]))
        assert "SSH_AUTH_SOCK" in child and not child & (ISOLATION | TAGS), child

    def test_a_push_from_another_agent_is_not_stopped_by_our_hook(
        self, rig_factory, opencode_bin
    ) -> None:
        rig = installed(rig_factory, opencode_bin, env={})
        remote = add_origin(rig)
        run_shell(rig, "git checkout -q -b feat/x", agent="build")
        out = run_shell(rig, "git push -q origin feat/x; echo rc=$?", agent="build")
        assert out.strip().endswith("rc=0"), out
        heads = subprocess.run(
            ["git", "-C", str(remote), "branch", "--list"], capture_output=True, text=True
        ).stdout
        assert "feat/x" in heads  # the hook only acts on the plugin's tag

    def test_the_bang_shell_is_still_the_humans(self, rig_factory, opencode_bin) -> None:
        rig = installed(rig_factory, opencode_bin, env={})
        run_shell(rig, "true")
        wait_status(rig, "passed")
        human = names_of(bang(rig, NAMES))
        assert "CARTER_HUMAN_SHELL" in human and "SSH_AUTH_SOCK" in human


WORKSPACE_FILES = {
    ".carter/carter.yaml": (
        "version: '2'\nworkspace: {name: ws, mode: single}\nagents: [engineer]\n"
    ),
    ".opencode/agents/carter-engineer-local.md": CARTER_E2E_AGENT_MD,
}


class TestWorkspaceScope:
    @pytest.fixture
    def rig(self, rig_factory, opencode_bin) -> Rig:
        return installed(rig_factory, opencode_bin, env={}, ws_files=WORKSPACE_FILES)

    def test_every_agent_is_covered_inside_a_carter_workspace(self, rig: Rig) -> None:
        theirs = names_of(run_shell(rig, NAMES, agent="build"))
        assert theirs >= ISOLATION and not theirs & {"SSH_AUTH_SOCK", "GITHUB_TOKEN"}, theirs
        witness = rig.ws / "ran"
        refused = error_message(run_shell(rig, f"git -C . push; touch {witness}", agent="build"))
        assert refused.startswith(REFUSED) and not witness.exists()

    def test_a_shell_outside_the_workspace_is_untouched(self, rig: Rig) -> None:
        outside = rig.base / "elsewhere"
        outside.mkdir()
        got = names_of(force_shell(rig, NAMES, agent="build", workdir=outside))
        assert {"SSH_AUTH_SOCK", "GITHUB_TOKEN"} <= got and not got & (ISOLATION | TAGS), got
        witness = outside / "ran"
        out = force_shell(rig, f"git -C . push; touch {witness}", agent="build", workdir=outside)
        assert not error_message(out).startswith(REFUSED) and witness.exists()

    def test_a_directory_below_the_workspace_root_is_inside(self, rig: Rig) -> None:
        deep = rig.ws / "pkg" / "src"
        deep.mkdir(parents=True)
        got = names_of(force_shell(rig, NAMES, agent="build", workdir=deep))
        assert got >= ISOLATION, got


def test_the_server_env_the_rig_gives_the_plugin_is_the_one_the_tests_expect() -> None:
    assert {"SSH_AUTH_SOCK", "GITHUB_TOKEN"} <= set(SERVER_ENV)
