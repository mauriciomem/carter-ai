# ruff: noqa: E501
"""The hook coverage matrix with the installed guard.

``tests/data/hook_matrix.json`` is the table of which hooks fire for every way a commit comes
into being, git 2.56). Here the *installed* ``carter-guard`` runs as config hooks next to a
recorder, in an agent shell with the T2 signing block and a throwaway agent:

* the clean agent flow produces exactly the recorded hooks, refs and signed commits, every commit
  that passed ``prepare-commit-msg`` carries one trailer;
* on every path where ``prepare-commit-msg`` fires, a wrong committer, a signing override at T2 and
  a signing attempt at T1 are rejected before a commit exists;
* the paths no Carter hook sees (the ``unhooked`` list of the data file) are pinned with their
  documented fallback: the gate refuses the plumbing verbs and ``check_signatures`` (the A+/B
  choke point) catches the unsigned LLM commit;
* a guard hook that fails mid-rebase leaves git's normal "rebase stopped" state.

The data is reviewed; a change of git behaviour shows up as a diff here (and in CI ``git-old``).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from carter.aplus.sigcheck import SigIdentity, check_signatures
from carter.gate import check as gate_check
from carter.guard import hooks
from carter.identity.errors import E_B_UNSIGNED
from guard.test_carter_guard_commit_events import EMAIL, World, with_config
from guard.test_git_behaviour_signing import (
    MATRIX,
    MODES,
    NV,
    SIGNING_ONLY,
    Lab,
    _summarise_hooks,
    needs_config_hooks,
    scenarios,
)
from ssh_rig import KeyPair, real_ssh

CARTER_EVENTS = ("prepare-commit-msg", "commit-msg", "post-commit")
DATA: dict[str, Any] = json.loads(MATRIX.read_text())
# Every path in the data file is replayed with CARTER_SSH_MATRIX=1 (about 2 minutes: a real agent and
# a signature per commit); a normal run replays the paths that cover each kind of hook sequence.
FULL = os.environ.get("CARTER_SSH_MATRIX") == "1"
REPRESENTATIVE = [
    "commit -m", "commit (editor)", "commit -C HEAD", "commit --amend --no-edit", "merge fast-forward",
    "merge --no-ff", "merge --squash + commit", "cherry-pick", "revert", "rebase (non-interactive)",
    "rebase -i reword", "stash push", "commit-tree -S", "am",
]  # fmt: skip
OPS = list(DATA["ops"]) if FULL else REPRESENTATIVE
EVIL = "evil@example.invalid"


class GuardLab(Lab):
    """The recording lab plus Carter's own config hooks, the agent env and the T2 block."""

    def __init__(self, root: Path, world: World, tier: str = "t2") -> None:
        super().__init__(root)
        self.world = world
        world.repo = self.repo
        world.configure(tier)
        script = hooks.script_path(None)
        for key, value in hooks.hook_entries(script, hooks.EVENTS):
            done = subprocess.run(
                ["git", "config", "--file", os.environ["GIT_CONFIG_GLOBAL"], "--add", key, value],
                capture_output=True, text=True,
            )  # fmt: skip
            assert done.returncode == 0, done.stderr
        self.extra_env = world.env()
        self.email = EMAIL

    def git(  # type: ignore[override]
        self, *args: str, env: dict[str, str] | None = None, llm: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Like ``Lab.git`` but the agent environment is the plugin's whole block."""
        full = {**os.environ}
        if llm:
            full.update(self.extra_env)
        full.update(env or {})
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=full, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=60, start_new_session=True, check=False,
        )  # fmt: skip

    def new_commits(self, shas: set[str], post_heads: list[str]) -> list[dict[str, Any]]:
        out = []
        for sha in sorted(shas):
            head = self.git("cat-file", "commit", sha, llm=False).stdout.split("\n\n", 1)[0]
            committer = next(x for x in head.splitlines() if x.startswith("committer "))
            out.append(
                {
                    "llm": self.email in committer,
                    "signed": "gpgsig " in head,
                    "post_commit": sha in post_heads,
                }
            )
        return out

    def run(self, name: str, mode: str) -> dict[str, Any] | None:
        setup, nv_ok, steps = scenarios(self)[name]
        if mode == "no-verify" and not nv_ok:
            return None
        setup()
        self.reset_log()
        before = self.commits()
        opts = ["-c", "core.hooksPath=/dev/null"] if mode.startswith("hooksPath") else []
        results, stdout_shas = [], set()
        tree = self.git("rev-parse", "HEAD^{tree}", llm=False).stdout.strip()
        for step in steps:
            if step == "resolve":
                self.resolve()
                continue
            if step == "checkout-feat":
                self.git("checkout", "-q", "feat", llm=False)
                continue
            env = step[-1] if isinstance(step[-1], dict) else None
            flat: list[str] = []
            for arg in step:
                if isinstance(arg, dict):
                    continue
                flat += (
                    ([NV] if mode == "no-verify" else [])
                    if arg == "@NV"
                    else [tree]
                    if arg == "@TREE"
                    else [str(next((self.root / "patches").glob("*.patch")))]
                    if arg == "@PATCH"
                    else [arg]
                )
            done = self.git(*opts, *flat, env=env)
            results.append(done)
            if name.startswith("commit-tree") and done.stdout.strip():
                stdout_shas.add(done.stdout.strip())
        hooks_fired, post_heads, refs = _summarise_hooks(self)
        new = self.new_commits((self.commits() | stdout_shas) - before, post_heads)
        return {
            "rc": [r.returncode for r in results],
            "hooks": hooks_fired,
            "refs": refs,
            "new": new,
            "stderr": "\n".join(r.stderr for r in results),
            "shas": sorted((self.commits() | stdout_shas) - before),
        }


# the lab's editor appends a line after the message: the trailer stops being the last paragraph
EDITOR_APPENDS = {"commit (editor)", "commit -t template"}
# the lab's reword editor replaces the whole message: the trailer is gone with it
EDITOR_REWRITES = {"rebase -i reword"}
# an agent may not change a commit's author, so the hook refuses this one (it is also
# on the gate's forbidden list); the recorded data is the git behaviour without Carter's rule.
AUTHOR_CHANGERS = {"commit --amend --reset-author"}


def comparable(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: entry[k] for k in ("rc", "hooks", "refs")} | {
        "new": [{k: c[k] for k in ("llm", "post_commit", "signed")} for c in entry["new"]]
    }


@pytest.fixture
def world(tmp_path: Path, throwaway_key: Callable[..., KeyPair], real_ssh_agent) -> World:  # type: ignore[no-untyped-def]
    key = throwaway_key("ed25519")
    assert real_ssh_agent.add(key) == 0
    return World(Path(os.environ["HOME"]), tmp_path / "unused", key, str(real_ssh_agent.sock))


def fired(entry: dict[str, Any]) -> set[str]:
    return {h.split(":")[0] for h in entry["hooks"]}


def trailers(lab: GuardLab, sha: str) -> int:
    return lab.git("log", "-1", "--format=%B", sha, llm=False).stdout.count("Co-authored-by:")


@needs_config_hooks
@real_ssh
class TestCleanAgentFlow:
    @pytest.mark.parametrize("name", OPS)
    def test_the_installed_guard_changes_neither_hooks_nor_refs_and_commits_stay_signed(
        self, tmp_path: Path, world: World, name: str
    ) -> None:
        lab = GuardLab(tmp_path / "lab", world)
        for mode in MODES:
            got = lab.run(name, mode)
            want = DATA["ops"][name].get(mode)
            assert (got is None) == (want is None), (name, mode)
            if got is None or want is None:
                continue
            if name in AUTHOR_CHANGERS:
                assert got["rc"] != want["rc"], (name, mode)
                assert "may not change a commit's author" in got["stderr"], (name, mode)
                assert not any(c["llm"] for c in got["new"]), (name, mode)
                continue
            if name in EDITOR_APPENDS | EDITOR_REWRITES and "commit-msg" in fired(want):
                # the editor put text after the trailer: it is no longer in the last paragraph, so
                # GitHub would not credit it, and commit-msg says so (nothing is committed)
                assert (
                    got["rc"] != want["rc"] and "Co-authored-by trailer missing" in got["stderr"]
                ), (name, mode)
                if name in EDITOR_APPENDS:
                    assert not any(c["llm"] for c in got["new"]), (name, mode)
                continue
            assert got["rc"] == want["rc"], (name, mode, got["stderr"])
            assert comparable(got) == comparable(want), (name, mode)
            if mode == "no-verify" and name in EDITOR_REWRITES:
                # the documented gap: --no-verify skips commit-msg, so the reword editor can drop the
                # trailer; the signature and committer checks are in prepare-commit-msg and held
                assert not all(trailers(lab, s) for s in got["shas"]), (name, mode)
            if "prepare-commit-msg" in fired(got) and all(r == 0 for r in got["rc"]):
                llm = [s for s, c in zip(got["shas"], got["new"], strict=True) if c["llm"]]
                assert all(trailers(lab, s) >= 1 for s in llm), (name, mode)

    @pytest.mark.parametrize(
        "name",
        [
            "commit -m",
            "commit --amend --no-edit",
            "merge --no-ff",
            "rebase -i reword",
            "cherry-pick",
            "revert",
        ],
    )
    def test_the_trailer_is_there_exactly_once_on_the_hooked_paths(
        self, tmp_path: Path, world: World, name: str
    ) -> None:
        lab = GuardLab(tmp_path / "lab", world)
        got = lab.run(name, "default")
        assert got is not None
        llm = [s for s, c in zip(got["shas"], got["new"], strict=True) if c["llm"]]
        assert llm and all(trailers(lab, s) == 1 for s in llm), name


HOOKED = [
    n
    for n, m in DATA["ops"].items()
    if (FULL or n in REPRESENTATIVE)
    and "prepare-commit-msg" in {h.split(":")[0] for h in m["default"]["hooks"]}
    and m["default"]["new"]
    and n not in SIGNING_ONLY
]


def tamper(lab: GuardLab, kind: str) -> None:
    if kind == "committer":
        lab.extra_env = {**lab.extra_env, "GIT_COMMITTER_EMAIL": EVIL}
    elif kind == "gpgsign-off":
        lab.extra_env = with_config(lab.extra_env, commit__gpgsign="false")
    elif kind == "t1-signing":
        lab.extra_env = with_config(lab.extra_env, commit__gpgsign="true")


@needs_config_hooks
@real_ssh
class TestRejectsOnEveryHookedPath:
    @pytest.mark.parametrize("name", HOOKED)
    @pytest.mark.parametrize("kind", ["committer", "gpgsign-off"])
    def test_a_wrong_committer_or_an_unsigned_attempt_at_t2_makes_no_commit(
        self, tmp_path: Path, world: World, name: str, kind: str
    ) -> None:
        lab = GuardLab(tmp_path / "lab", world)
        lab.run(name, "default")  # (warm: the same scenario once clean, to know the clean count)
        lab.base()
        tamper(lab, kind)
        got = lab.run(name, "default")
        assert got is not None
        assert any(rc != 0 for rc in got["rc"]), (name, kind, "nothing was rejected")
        assert not any(
            c["llm"] and c["signed"] is False and kind == "gpgsign-off" for c in got["new"]
        ), (name, kind)
        assert EVIL not in lab.git("log", "--all", "--format=%ce", llm=False).stdout, name
        assert "carter-guard" in got["stderr"], (name, kind, got["stderr"])

    @pytest.mark.parametrize("name", HOOKED)
    def test_signing_is_rejected_at_t1(self, tmp_path: Path, world: World, name: str) -> None:
        lab = GuardLab(tmp_path / "lab", world, tier="t1")
        lab.extra_env = with_config(lab.extra_env, commit__gpgsign="true")
        got = lab.run(name, "default")
        assert got is not None
        assert any(rc != 0 for rc in got["rc"]) and "Signing attempted below T2" in got["stderr"], (
            name,
            got["stderr"],
        )


UNHOOKED = DATA["unhooked"]["no_carter_hook_at_all"]


@needs_config_hooks
@real_ssh
class TestPathsNoHookSees:
    def test_the_list_is_the_one_in_the_data_file(self) -> None:
        assert UNHOOKED == ["stash push", "commit-tree", "commit-tree -S", "notes add", "am"]

    @pytest.mark.parametrize("name", UNHOOKED)
    def test_no_carter_hook_fires_the_commit_exists_and_the_choke_point_decides(
        self, tmp_path: Path, world: World, name: str
    ) -> None:
        lab = GuardLab(tmp_path / "lab", world)
        got = lab.run(name, "default")
        assert got is not None and got["new"], name
        assert not fired(got) & set(CARTER_EVENTS), name
        ident = SigIdentity(
            email=EMAIL, public_keys=(world.key.blob,), fingerprints=(world.key.fingerprint,)
        )  # type: ignore[union-attr]
        findings = check_signatures(lab.repo, got["shas"], ident)
        flagged = {f.key for f in findings}
        for sha, c in zip(got["shas"], got["new"], strict=True):
            if c["llm"] and not c["signed"]:
                assert sha in flagged, (
                    name,
                    "an unsigned LLM commit slipped past check_signatures",
                )
            if c["signed"]:
                assert sha not in flagged, (name, "a good signature was flagged")
        assert all(f.code == E_B_UNSIGNED for f in findings)

    def test_the_gate_refuses_the_plumbing_verbs_in_agent_shells(self) -> None:
        for command in (
            "git commit-tree abc -p HEAD -m x",
            "git commit-tree -S abc -m x",
            "git fast-import",
        ):
            decision = gate_check(command)
            assert decision.decision == "deny" and decision.rule == "plumbing", command

    def test_what_the_gate_allows_among_them_is_pinned(self) -> None:
        """stash and notes commits are never signed by git and never pushed (refs/stash and
        refs/notes are not pushed by `carter push`); `am` honours commit.gpgsign, so it is signed."""
        for command in ("git stash push", "git notes add -m x HEAD", "git am p.patch"):
            assert gate_check(command).decision == "allow", command
        assert "stash push" in DATA["unhooked"]["no_carter_hook_at_all"]


@needs_config_hooks
@real_ssh
class TestAFailingGuardMidRebase:
    def test_the_rebase_stops_in_gits_normal_state_and_can_be_aborted(
        self, tmp_path: Path, world: World
    ) -> None:
        lab = GuardLab(tmp_path / "lab", world)
        lab.branches(diverge=True)
        lab.git("checkout", "-q", "feat", llm=False)
        orig = lab.git("rev-parse", "HEAD", llm=False).stdout.strip()
        lab.extra_env = {**lab.extra_env, "GIT_COMMITTER_EMAIL": EVIL}
        done = lab.git("rebase", "main")
        assert done.returncode != 0 and "carter-guard" in done.stderr
        status = lab.git("status", "--porcelain=v2", "--branch", llm=False)
        assert status.returncode == 0 and (lab.repo / ".git" / "rebase-merge").is_dir()
        assert lab.git("fsck", "--no-dangling", llm=False).returncode == 0
        abort = lab.git("rebase", "--abort", llm=False)
        assert abort.returncode == 0 and not (lab.repo / ".git" / "rebase-merge").exists()
        assert lab.git("rev-parse", "HEAD", llm=False).stdout.strip() == orig

    def test_after_the_abort_the_humans_own_commit_works(
        self, tmp_path: Path, world: World
    ) -> None:
        lab = GuardLab(tmp_path / "lab", world)
        lab.branches(diverge=True)
        lab.git("checkout", "-q", "feat", llm=False)
        lab.extra_env = {**lab.extra_env, "GIT_COMMITTER_EMAIL": EVIL}
        assert lab.git("rebase", "main").returncode != 0
        assert lab.git("rebase", "--abort", llm=False).returncode == 0
        (lab.repo / "human.txt").write_text("h\n")
        lab.git("add", "-A", llm=False)
        done = lab.git(
            "commit",
            "-q",
            "-m",
            "human",
            env={
                "GIT_AUTHOR_NAME": "h",
                "GIT_AUTHOR_EMAIL": "h@e.invalid",
                "GIT_COMMITTER_NAME": "h",
                "GIT_COMMITTER_EMAIL": "h@e.invalid",
            },
            llm=False,
        )
        assert done.returncode == 0, done.stderr
