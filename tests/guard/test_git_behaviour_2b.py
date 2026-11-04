"""What git does that the slice-2b commit hooks and signing rely on (plan 005, step 3; spike B).

Observed on git 2.56.0, Linux, in the hermetic fixture home: config-based hooks (git >= 2.54),
local repos only, no network. ``tests/data/hook_matrix.json`` is the machine-readable result of
the hook coverage matrix (RFC-0007 section 9): for each way a commit can come into being, which
of Carter's hooks fire, and which new commits carrying the LLM as committer no hook saw.

* The matrix test replays every scenario **unsigned** and compares hooks, ref updates and
  which new commits ``post-commit`` saw. It runs wherever git has config hooks.
* The signed replay (``real_ssh_agent``, ``CARTER_SSH_MATRIX=1``) adds the signature flag
  through a real dedicated ``ssh-agent`` and a shim; regenerate the file with
  ``CARTER_REGEN_MATRIX=1 CARTER_SSH_MATRIX=1 pytest tests/guard/test_git_behaviour_2b.py``.

The remaining classes pin the signing contract (the exact argv git hands to ``gpg.ssh.program``),
precedence, trailers, the guard's config inputs, ``includeIf`` fragments, amend and the alias.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ssh_rig import Rig, real_ssh, signed_matrix

MATRIX = Path(__file__).resolve().parent.parent / "data" / "hook_matrix.json"
EVENTS = (
    "pre-commit",
    "prepare-commit-msg",
    "commit-msg",
    "post-commit",
    "pre-merge-commit",
    "post-merge",
    "post-rewrite",
    "applypatch-msg",
    "post-applypatch",
    "reference-transaction",
)
LLM = ("LLM Agent", "llm@example.invalid")
SETUP_ENV = {
    "GIT_AUTHOR_NAME": "Setup",
    "GIT_AUTHOR_EMAIL": "setup@example.invalid",
    "GIT_COMMITTER_NAME": "Setup",
    "GIT_COMMITTER_EMAIL": "setup@example.invalid",
}


def git_version() -> tuple[int, int]:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


GIT = git_version()
needs_config_hooks = pytest.mark.skipif(GIT < (2, 54), reason="config-based hooks need git >= 2.54")


def counted(*pairs: tuple[str, str]) -> dict[str, str]:
    env = {"GIT_CONFIG_COUNT": str(len(pairs))}
    for i, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


class Lab:
    """A repo in the hermetic home with recording config hooks and the LLM as committer."""

    def __init__(self, root: Path, extra_env: dict[str, str] | None = None) -> None:
        self.root = root
        self.repo = root / "repo"
        self.log = root / "hooks.log"
        self.extra_env = extra_env or {}
        self.root.mkdir(parents=True, exist_ok=True)
        rec = root / "rec.sh"
        rec.write_text(
            "#!/bin/sh\n"
            'name="$1"; shift\n'
            'if [ "$name" = reference-transaction ]; then\n'
            "  state=\"$1\"; refs=$(awk '{print $3}' | tr '\\n' ',')\n"
            '  [ "$state" = committed ] && '
            f"printf 'reference-transaction|x|%s\\n' \"$refs\" >> '{self.log}'\n"
            "  exit 0\n"
            "fi\n"
            "head=$(git rev-parse -q --verify HEAD 2>/dev/null || echo none)\n"
            f'printf \'%s|%s|%s\\n\' "$name" "$head" "$*" >> \'{self.log}\'\n'
        )
        rec.chmod(0o755)
        with Path(os.environ["GIT_CONFIG_GLOBAL"]).open("a") as handle:
            for event in EVENTS:
                handle.write(
                    f'[hook "rec-{event}"]\n\tevent = {event}\n\tcommand = "{rec} {event}"\n'
                )
        for name, body in (
            ("edit-append.sh", "printf '\\nedited by editor\\n' >> \"$1\""),
            ("editor-reword.sh", "printf 'reworded\\n' > \"$1\""),
            ("seq-reword.sh", "sed -i '1s/^pick/reword/' \"$1\""),
            ("seq-squash.sh", "sed -i '2s/^pick/squash/' \"$1\""),
            ("seq-fixup.sh", "sed -i '2s/^pick/fixup/' \"$1\""),
            ("seq-pick.sh", ":"),
        ):
            script = root / name
            script.write_text(f"#!/bin/sh\n{body}\n")
            script.chmod(0o755)

    # -- git ---------------------------------------------------------------------------------
    def git(
        self, *args: str, env: dict[str, str] | None = None, llm: bool = True
    ) -> subprocess.CompletedProcess[str]:
        full = {**os.environ}
        if llm:
            full.update(GIT_COMMITTER_NAME=LLM[0], GIT_COMMITTER_EMAIL=LLM[1], **self.extra_env)
        full.update(env or {})
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=full,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            start_new_session=True,
            check=False,
        )

    def setup_commit(self, message: str, files: dict[str, str]) -> None:
        for name, text in files.items():
            (self.repo / name).write_text(text)
        self.git("add", "-A", llm=False)
        done = self.git("commit", "-q", "-m", message, env=SETUP_ENV, llm=False)
        assert done.returncode == 0, done.stderr

    def commits(self) -> set[str]:
        return set(self.git("rev-list", "--all", "--reflog", llm=False).stdout.split())

    def reset_log(self) -> None:
        self.log.write_text("")

    # -- setups ------------------------------------------------------------------------------
    def init(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main", llm=False)

    def base(self) -> None:
        self.init()
        self.setup_commit("base", {"a.txt": "a\n"})

    def change(self) -> None:
        self.base()
        (self.repo / "a.txt").write_text("a\nchange\n")
        self.git("add", "-A", llm=False)

    def branches(self, *, diverge: bool, conflict: bool = False) -> None:
        self.base()
        self.git("checkout", "-q", "-b", "feat", llm=False)
        self.setup_commit("feat1", {"a.txt": "feat\n"} if conflict else {"f.txt": "f1\n"})
        self.setup_commit("feat2", {"g.txt": "g\n"})
        self.git("checkout", "-q", "main", llm=False)
        if diverge:
            self.setup_commit("main1", {"a.txt": "main\n"} if conflict else {"m.txt": "m\n"})

    def two_commits(self) -> None:
        self.base()
        self.setup_commit("two", {"b.txt": "b\n"})

    def dirty(self) -> None:
        self.base()
        (self.repo / "a.txt").write_text("dirty\n")

    def patch(self) -> None:
        self.branches(diverge=True)
        out = self.root / "patches"
        shutil.rmtree(out, ignore_errors=True)
        self.git("format-patch", "-1", "feat", "-o", str(out), llm=False)

    def resolve(self) -> None:
        (self.repo / "a.txt").write_text("resolved\n")
        self.git("add", "-A", llm=False)


NV = "--no-verify"
Step = tuple[str, ...]


def scenarios(lab: Lab) -> dict[str, tuple[Callable[[], None], bool, list[Any]]]:
    """name -> (setup, supports --no-verify, steps). A step is an argv tuple (git arguments,
    ``@NV`` marks where --no-verify goes, ``@TREE`` the tree id, ``@PATCH`` the patch file),
    optionally followed by an env dict; the strings ``resolve`` and ``checkout-feat`` are
    helpers."""
    ed = {"GIT_EDITOR": str(lab.root / "edit-append.sh")}
    true = {"GIT_EDITOR": "true"}
    seq = lambda name, editor: {  # noqa: E731
        "GIT_SEQUENCE_EDITOR": str(lab.root / name),
        "GIT_EDITOR": editor,
    }
    reword = str(lab.root / "editor-reword.sh")
    tpl = str(lab.root / "tpl.txt")
    msg = str(lab.root / "msg.txt")
    (lab.root / "tpl.txt").write_text("template line\n")
    (lab.root / "msg.txt").write_text("from file\n")
    return {
        "commit -m": (lab.change, True, [("commit", "-m", "llm msg", "@NV")]),
        "commit -F file": (lab.change, True, [("commit", "-F", msg, "@NV")]),
        "commit (editor)": (lab.change, True, [("commit", "@NV", ed)]),
        "commit -t template": (lab.change, True, [("commit", "-t", tpl, "@NV", ed)]),
        "commit -C HEAD": (lab.change, True, [("commit", "-C", "HEAD", "@NV")]),
        "commit --amend": (lab.base, True, [("commit", "--amend", "-m", "amended", "@NV")]),
        "commit --amend --no-edit": (lab.base, True, [("commit", "--amend", "--no-edit", "@NV")]),
        "commit --amend --reset-author": (
            lab.base,
            True,
            [("commit", "--amend", "--no-edit", "--reset-author", "@NV")],
        ),
        "commit --fixup": (lab.change, True, [("commit", "--fixup", "HEAD", "@NV")]),
        "commit --allow-empty": (lab.base, True, [("commit", "--allow-empty", "-m", "e", "@NV")]),
        "merge fast-forward": (
            lambda: lab.branches(diverge=False),
            True,
            [("merge", "--ff-only", "feat", "@NV")],
        ),
        "merge --no-ff": (
            lambda: lab.branches(diverge=True),
            True,
            [("merge", "--no-ff", "--no-edit", "feat", "@NV", true)],
        ),
        "merge --no-ff (editor)": (
            lambda: lab.branches(diverge=True),
            True,
            [("merge", "--no-ff", "feat", "@NV", ed)],
        ),
        "merge conflict + merge --continue": (
            lambda: lab.branches(diverge=True, conflict=True),
            True,
            [("merge", "feat", "@NV", true), "resolve", ("merge", "--continue", true)],
        ),
        "merge conflict + commit": (
            lambda: lab.branches(diverge=True, conflict=True),
            True,
            [("merge", "feat", "@NV", true), "resolve", ("commit", "--no-edit", "@NV", true)],
        ),
        "merge --squash + commit": (
            lambda: lab.branches(diverge=True),
            True,
            [("merge", "--squash", "feat"), ("commit", "--no-edit", "@NV", true)],
        ),
        "cherry-pick": (lambda: lab.branches(diverge=True), True, [("cherry-pick", "feat")]),
        "cherry-pick -e": (
            lambda: lab.branches(diverge=True),
            True,
            [("cherry-pick", "-e", "feat", ed)],
        ),
        "cherry-pick conflict + --continue": (
            lambda: lab.branches(diverge=True, conflict=True),
            True,
            [("cherry-pick", "feat~1"), "resolve", ("cherry-pick", "--continue", true)],
        ),
        "cherry-pick -n + commit": (
            lambda: lab.branches(diverge=True),
            True,
            [("cherry-pick", "-n", "feat"), ("commit", "-m", "after -n", "@NV")],
        ),
        "revert": (lab.two_commits, True, [("revert", "--no-edit", "HEAD", true)]),
        "revert -e": (lab.two_commits, True, [("revert", "-e", "HEAD", ed)]),
        "rebase (non-interactive)": (
            lambda: lab.branches(diverge=True),
            True,
            ["checkout-feat", ("rebase", "main", "@NV")],
        ),
        "rebase -i reword": (
            lambda: lab.branches(diverge=True),
            True,
            ["checkout-feat", ("rebase", "-i", "main", "@NV", seq("seq-reword.sh", reword))],
        ),
        "rebase -i squash": (
            lambda: lab.branches(diverge=True),
            True,
            ["checkout-feat", ("rebase", "-i", "main", "@NV", seq("seq-squash.sh", "true"))],
        ),
        "rebase -i fixup": (
            lambda: lab.branches(diverge=True),
            True,
            ["checkout-feat", ("rebase", "-i", "main", "@NV", seq("seq-fixup.sh", "true"))],
        ),
        "rebase -i pick only": (
            lambda: lab.branches(diverge=True),
            True,
            ["checkout-feat", ("rebase", "-i", "main", "@NV", seq("seq-pick.sh", "true"))],
        ),
        "stash push": (lab.dirty, False, [("stash", "push")]),
        "stash push + pop": (lab.dirty, False, [("stash", "push"), ("stash", "pop")]),
        "commit-tree": (
            lab.base,
            False,
            [("commit-tree", "@TREE", "-p", "HEAD", "-m", "plumbing")],
        ),
        "commit-tree -S": (
            lab.base,
            False,
            [("commit-tree", "-S", "@TREE", "-p", "HEAD", "-m", "plumbing")],
        ),
        "notes add": (lab.base, False, [("notes", "add", "-m", "a note", "HEAD")]),
        "am": (lab.patch, True, [("am", "@NV", "@PATCH")]),
        "tag -a (no commit)": (lab.base, False, [("tag", "-a", "t1", "-m", "tag")]),
        "tag -s": (lab.base, False, [("tag", "-s", "t2", "-m", "stag")]),
    }


MODES = ("default", "no-verify", "hooksPath=/dev/null")
SIGNING_ONLY = ("commit-tree -S", "tag -s")  # they fail without a signing key: signed replay only


def _summarise_hooks(lab: Lab) -> tuple[list[str], list[str], list[str]]:
    hooks: list[str] = []
    post_heads: list[str] = []
    refs: set[str] = set()
    for line in lab.log.read_text().splitlines():
        name, head, args = (line.split("|", 2) + ["", ""])[:3]
        words = args.split()
        if name == "prepare-commit-msg":
            hooks.append("prepare-commit-msg:" + (words[1] if len(words) > 1 else "message"))
        elif name == "post-rewrite":
            hooks.append("post-rewrite:" + (words[0] if words else ""))
        elif name == "reference-transaction":
            refs.update(r for r in args.split(",") if r.startswith("refs/"))
        else:
            hooks.append(name)
        if name == "post-commit":
            post_heads.append(head)
    return hooks, post_heads, sorted(refs)


def _new_commits(lab: Lab, shas: set[str], post_heads: list[str]) -> list[dict[str, Any]]:
    out = []
    for sha in sorted(shas):
        head = lab.git("cat-file", "commit", sha, llm=False).stdout.split("\n\n", 1)[0]
        committer = next(x for x in head.splitlines() if x.startswith("committer "))
        out.append(
            {
                "llm": LLM[1] in committer,
                "signed": "gpgsig " in head,
                "post_commit": sha in post_heads,
            }
        )
    return out


def run_scenario(lab: Lab, name: str, mode: str) -> dict[str, Any] | None:
    setup, nv_ok, steps = scenarios(lab)[name]
    if mode == "no-verify" and not nv_ok:
        return None
    setup()
    lab.reset_log()
    before = lab.commits()
    opts = ["-c", "core.hooksPath=/dev/null"] if mode.startswith("hooksPath") else []
    results = []
    stdout_shas: set[str] = set()
    tree = lab.git("rev-parse", "HEAD^{tree}", llm=False).stdout.strip()
    for step in steps:
        if step == "resolve":
            lab.resolve()
            continue
        if step == "checkout-feat":
            lab.git("checkout", "-q", "feat", llm=False)
            continue
        env = step[-1] if isinstance(step[-1], dict) else None
        flat: list[str] = []
        for arg in step:
            if isinstance(arg, dict):
                continue
            if arg == "@NV":
                flat.extend([NV] if mode == "no-verify" else [])
            elif arg == "@TREE":
                flat.append(tree)
            elif arg == "@PATCH":
                flat.append(str(next((lab.root / "patches").glob("*.patch"))))
            else:
                flat.append(arg)
        done = lab.git(*opts, *flat, env=env)
        results.append(done)
        if name.startswith("commit-tree") and done.stdout.strip():
            stdout_shas.add(done.stdout.strip())
    hooks, post_heads, refs = _summarise_hooks(lab)
    new = _new_commits(lab, (lab.commits() | stdout_shas) - before, post_heads)
    return {"rc": [r.returncode for r in results], "hooks": hooks, "refs": refs, "new": new}


def build_matrix(lab: Lab) -> dict[str, Any]:
    ops: dict[str, Any] = {}
    for name in scenarios(lab):
        ops[name] = {}
        for mode in MODES:
            entry = run_scenario(lab, name, mode)
            if entry is not None:
                ops[name][mode] = entry
    return {
        "git": ".".join(map(str, GIT)),
        "events": list(EVENTS),
        "modes": list(MODES),
        "ops": ops,
    }


def unhooked(matrix: dict[str, Any]) -> dict[str, list[str]]:
    """Default-mode ops that create a commit by the LLM that a given hook never saw."""
    out: dict[str, list[str]] = {
        "no_commit_msg": [],
        "no_prepare_commit_msg": [],
        "no_post_commit": [],
        "no_carter_hook_at_all": [],
    }
    carter = ("prepare-commit-msg", "commit-msg", "post-commit")
    for name, modes in matrix["ops"].items():
        entry = modes["default"]
        if not any(c["llm"] for c in entry["new"]):
            continue
        fired = {h.split(":")[0] for h in entry["hooks"]}
        for key, hook in (
            ("no_commit_msg", "commit-msg"),
            ("no_prepare_commit_msg", "prepare-commit-msg"),
            ("no_post_commit", "post-commit"),
        ):
            if hook not in fired:
                out[key].append(name)
        if not fired & set(carter):
            out["no_carter_hook_at_all"].append(name)
    return out


def comparable(entry: dict[str, Any], *, signed: bool) -> dict[str, Any]:
    keep = ("llm", "post_commit", "signed") if signed else ("llm", "post_commit")
    return {
        "rc": entry["rc"],
        "hooks": entry["hooks"],
        "refs": entry["refs"],
        "new": [{k: c[k] for k in keep} for c in entry["new"]],
    }


@needs_config_hooks
class TestHookMatrix:
    def test_every_scenario_matches_the_recorded_matrix(self, tmp_path: Path) -> None:
        recorded = json.loads(MATRIX.read_text())
        lab = Lab(tmp_path / "lab")
        fresh = build_matrix(lab)
        got, want = (
            {
                n: {m: comparable(e, signed=False) for m, e in ms.items()}
                for n, ms in doc["ops"].items()
                if n not in SIGNING_ONLY
            }
            for doc in (fresh, recorded)
        )
        assert got == want

    def test_the_unhooked_summary_is_derived_from_the_matrix(self) -> None:
        recorded = json.loads(MATRIX.read_text())
        assert recorded["unhooked"] == unhooked(recorded)

    def test_the_findings_the_hooks_design_depends_on(self) -> None:
        ops = json.loads(MATRIX.read_text())["ops"]
        default = {n: m["default"]["hooks"] for n, m in ops.items()}
        # --no-verify skips pre-commit and commit-msg only; prepare-commit-msg and post-commit stay
        assert "commit-msg" in default["commit -m"]
        assert ops["commit -m"]["no-verify"]["hooks"] == [
            "prepare-commit-msg:message",
            "post-commit",
        ]
        # config hooks survive -c core.hooksPath=/dev/null
        assert ops["commit -m"]["hooksPath=/dev/null"]["hooks"] == default["commit -m"]
        # cherry-pick, revert and rebase picks: prepare-commit-msg and post-commit, no commit-msg
        for name in ("cherry-pick", "revert", "rebase (non-interactive)"):
            assert "commit-msg" not in default[name] and "post-commit" in default[name]
        assert "prepare-commit-msg:message" in default["rebase (non-interactive)"]
        # a --no-ff merge commit gets commit-msg but post-merge replaces post-commit
        assert (
            "commit-msg" in default["merge --no-ff"]
            and "post-commit" not in default["merge --no-ff"]
        )
        assert "post-merge" in default["merge --no-ff"]
        # a merge that stops on a conflict is committed by `git commit`: all three fire
        assert {"commit-msg", "post-commit"} <= set(default["merge conflict + commit"])
        # the merge source is passed as `merge`, a --squash message as `squash`, -C as `commit`
        assert "prepare-commit-msg:merge" in default["merge --no-ff"]
        assert "prepare-commit-msg:squash" in default["merge --squash + commit"]
        assert "prepare-commit-msg:commit" in default["commit -C HEAD"]
        assert "prepare-commit-msg:template" in default["commit -t template"]
        # amend fires post-rewrite:amend as well
        assert "post-rewrite:amend" in default["commit --amend"]

    def test_commits_no_hook_of_ours_ever_sees(self) -> None:
        matrix = json.loads(MATRIX.read_text())
        none = matrix["unhooked"]["no_carter_hook_at_all"]
        assert none == ["stash push", "commit-tree", "commit-tree -S", "notes add", "am"]
        # ... but every one that moves a ref is seen by reference-transaction, the only net that
        # does (a bare commit-tree object is dangling until `update-ref`, which the gate forbids)
        for name in none:
            moves = bool(matrix["ops"][name]["default"]["refs"])
            assert moves is not name.startswith("commit-tree"), name
        # stash and notes commits stay unsigned even with commit.gpgsign (not user commits)
        for name in ("stash push", "notes add", "commit-tree"):
            assert not any(c["signed"] for c in matrix["ops"][name]["default"]["new"]), name
        # plain commit-tree ignores commit.gpgsign: only -S signs it
        assert all(c["signed"] for c in matrix["ops"]["commit-tree -S"]["default"]["new"])
        # `am` honours commit.gpgsign but runs applypatch hooks, not ours
        assert all(c["signed"] for c in matrix["ops"]["am"]["default"]["new"])
        assert not {"commit-msg", "post-commit", "prepare-commit-msg"} & {
            h.split(":")[0] for h in matrix["ops"]["am"]["default"]["hooks"]
        }


@needs_config_hooks
@signed_matrix
class TestSignedMatrix:
    """The same scenarios with the signing block of the isolation env and a real agent."""

    def _lab(self, rig: Rig, tmp_path: Path) -> Lab:
        sock, _ = rig.start_agent()
        key = rig.keygen("llm")
        assert rig.run("ssh-add", str(key), sock=sock).returncode == 0
        kind, blob = (rig.root / "keys" / "llm.pub").read_text().split()[:2]
        shim = rig.root / "shim"
        shim.write_text(
            f"#!/bin/sh\nexec env SSH_AUTH_SOCK='{sock}' SSH_ASKPASS=/usr/bin/false "
            f'SSH_ASKPASS_REQUIRE=force /usr/bin/ssh-keygen "$@"\n'
        )
        shim.chmod(0o755)
        allowed = rig.root / "allowed_signers"
        allowed.write_text(f'llm@example.invalid namespaces="git" {kind} {blob}\n')
        env = counted(
            ("commit.gpgsign", "true"),
            ("gpg.format", "ssh"),
            ("user.signingkey", f"key::{kind} {blob}"),
            ("gpg.ssh.program", str(shim)),
            ("gpg.ssh.allowedSignersFile", str(allowed)),
        )
        return Lab(tmp_path / "lab", extra_env=env)

    def test_signature_flags_match_the_recorded_matrix(self, rig: Rig, tmp_path: Path) -> None:
        lab = self._lab(rig, tmp_path)
        fresh = build_matrix(lab)
        if os.environ.get("CARTER_REGEN_MATRIX") == "1":
            fresh["unhooked"] = unhooked(fresh)
            MATRIX.write_text(json.dumps(fresh, indent=1) + "\n")
            return
        recorded = json.loads(MATRIX.read_text())
        got = {
            n: {m: comparable(e, signed=True) for m, e in ms.items()}
            for n, ms in fresh["ops"].items()
        }
        want = {
            n: {m: comparable(e, signed=True) for m, e in ms.items()}
            for n, ms in recorded["ops"].items()
        }
        assert got == want


# --- 2. the signing contract: what git hands to gpg.ssh.program -----------------------------------


@real_ssh
class TestSigningContract:
    """The exact argv of the shim, and the model-visible failures (RFC App B, App C.3)."""

    @staticmethod
    def _setup(rig: Rig, tmp_path: Path) -> tuple[Path, Path, Path, Path, dict[str, str]]:
        sock, _ = rig.start_agent()
        key = rig.keygen("llm")
        rig.run("ssh-add", str(key), sock=sock)
        kind, blob = (rig.root / "keys" / "llm.pub").read_text().split()[:2]
        # a path with a space, as the shim may live under a home directory with one
        shim = rig.root / "shim dir" / "sign-shim"
        shim.parent.mkdir()
        log = rig.root / "shim.log"
        shim.write_text(
            "#!/bin/sh\n"
            '{ printf \'%s\' "$#"; for a in "$@"; do printf \' [%s]\' "$a"; done; echo; }'
            f" >> '{log}'\n"
            "prev=''; for a in \"$@\"; do\n"
            f"  [ \"$prev\" = -f ] && {{ printf 'F: '; cat \"$a\"; }} >> '{log}'; prev=$a; done\n"
            f"exec env SSH_AUTH_SOCK='{sock}' SSH_ASKPASS=/usr/bin/false "
            f'SSH_ASKPASS_REQUIRE=force /usr/bin/ssh-keygen "$@"\n'
        )
        shim.chmod(0o755)
        allowed = rig.root / "allowed_signers"
        allowed.write_text(f'llm@example.invalid namespaces="git" {kind} {blob}\n')
        env = counted(
            ("commit.gpgsign", "true"),
            ("gpg.format", "ssh"),
            ("user.signingkey", f"key::{kind} {blob}"),
            ("gpg.ssh.program", str(shim)),
            ("gpg.ssh.allowedSignersFile", str(allowed)),
        )
        return shim, log, allowed, sock, env

    def _repo(self, tmp_path: Path, env: dict[str, str]) -> Lab:
        lab = Lab(tmp_path / "lab", extra_env=env)
        lab.base()
        (lab.repo / "a.txt").write_text("a2\n")
        lab.git("add", "-A", llm=False)
        return lab

    @staticmethod
    def _argv(log: Path, root: Path) -> list[str]:
        text = re.sub(r"[^\s\[\]]*/(\.git_\w+)", r"<tmp>/\1", log.read_text())
        return text.replace(str(root), "<root>").splitlines()

    def test_sign_argv_has_dash_u_and_the_literal_key_in_the_file(
        self,
        rig: Rig,
        tmp_path: Path,
    ) -> None:
        _, log, _, _, env = self._setup(rig, tmp_path)
        lab = self._repo(tmp_path, env)
        assert lab.git("commit", "-q", "-m", "s").returncode == 0
        first, second = self._argv(log, rig.root)[:2]
        # git >= 2.40 passes -U for a key:: literal; older git omits it (no agent signing)
        assert re.fullmatch(
            r"8 \[-Y\] \[sign\] \[-n\] \[git\] \[-f\] \[<tmp>/\.git_signing_key_tmp\w+\] \[-U\] "
            r"\[<tmp>/\.git_signing_buffer_tmp\w+\]",
            first,
        ), first
        kind, blob = (rig.root / "keys" / "llm.pub").read_text().split()[:2]
        assert second == f"F: {kind} {blob}"  # the key file holds exactly the configured literal
        assert rig.run("ssh-keygen", "-lf", str(rig.root / "keys" / "llm.pub")).returncode == 0

    def test_a_path_key_has_no_dash_u_and_a_comment_stays_in_the_file(
        self,
        rig: Rig,
        tmp_path: Path,
    ) -> None:
        _, log, _, _, env = self._setup(rig, tmp_path)
        pub = rig.root / "keys" / "llm.pub"
        lab = self._repo(tmp_path, {**env, "GIT_CONFIG_VALUE_2": str(pub)})
        assert lab.git("commit", "-q", "-m", "s").returncode == 0
        first, second = self._argv(log, rig.root)[:2]
        assert "[-U]" not in first and f"[{pub}]".replace(str(rig.root), "<root>") in first
        assert second.endswith(" spike")  # a .pub path keeps its comment: the shim must refuse it
        log.write_text("")
        lab2 = self._repo(tmp_path, env)
        kind, blob = pub.read_text().split()[:2]
        commented = {**env, "GIT_CONFIG_VALUE_2": f"key::{kind} {blob} some comment"}
        lab2.extra_env = commented
        assert lab2.git("commit", "-q", "-m", "s").returncode == 0
        assert self._argv(log, rig.root)[1] == f"F: {kind} {blob} some comment"

    def test_verify_argv_through_the_shim(self, rig: Rig, tmp_path: Path) -> None:
        shim, log, allowed, _, env = self._setup(rig, tmp_path)
        lab = self._repo(tmp_path, env)
        lab.git("commit", "-q", "-m", "s")
        log.write_text("")
        done = lab.git("verify-commit", "HEAD")
        assert (
            done.returncode == 0 and 'Good "git" signature for llm@example.invalid' in done.stderr
        )
        lines = [x for x in self._argv(log, rig.root) if not x.startswith("F:")]
        assert lines[0].startswith("7 [-Y] [find-principals] [-f] [<root>/allowed_signers]")
        assert lines[0].endswith("[-Overify-time=" + lines[0].split("verify-time=")[1])
        assert re.search(
            r"\[-Y\] \[verify\] \[-n\] \[git\] \[-f\] \[<root>/allowed_signers\] \[-I\] "
            r"\[llm@example.invalid\] \[-s\] \[<tmp>/\.git_vtag_tmp\w+\]",
            lines[1],
        )
        # a key the allowed_signers file does not know: find-principals fails, then check-novalidate
        stranger = rig.keygen("stranger")
        s_kind, s_blob = Path(f"{stranger}.pub").read_text().split()[:2]
        other = rig.root / "other_signers"
        other.write_text(f'x@example.invalid namespaces="git" {s_kind} {s_blob}\n')
        log.write_text("")
        env2 = {**env, "GIT_CONFIG_VALUE_4": str(other)}
        done = lab.git("verify-commit", "HEAD", env=env2)
        assert done.returncode == 1 and "No principal matched" in done.stderr
        ops = [re.search(r"\[-Y\] \[([\w-]+)\]", x) for x in self._argv(log, rig.root)]
        assert [m.group(1) for m in ops if m] == ["find-principals", "check-novalidate"]

    def test_verification_needs_allowed_signers_and_the_post_commit_view(
        self,
        rig: Rig,
        tmp_path: Path,
    ) -> None:
        _, log, _, _, env = self._setup(rig, tmp_path)
        lab = self._repo(tmp_path, env)
        lab.git("commit", "-q", "-m", "s")
        fp = rig.run("ssh-keygen", "-lf", str(rig.root / "keys" / "llm.pub")).stdout.split()[1]
        shown = lab.git("log", "-1", "--format=%G?|%GF|%GS").stdout.strip()
        assert shown == f"G|{fp}|llm@example.invalid"  # what post-commit sees (G, fingerprint)
        log.write_text("")
        bare = dict(env)
        bare["GIT_CONFIG_COUNT"] = "4"  # drop gpg.ssh.allowedSignersFile
        done = lab.git("verify-commit", "HEAD", env=bare)
        assert done.returncode == 1
        assert "allowedSignersFile needs to be configured and exist" in done.stderr
        assert log.read_text() == ""  # the shim is never reached

    def test_raw_errors_for_a_locked_stale_or_missing_agent_and_a_bad_program(
        self,
        rig: Rig,
        tmp_path: Path,
    ) -> None:
        _, _, _, sock, env = self._setup(rig, tmp_path)
        lab = self._repo(tmp_path, env)
        rig.run("ssh-add", "-D", sock=sock)  # locked / expired / wrong key: the same text
        done = lab.git("commit", "-q", "-m", "x")
        assert done.returncode == 128
        assert done.stderr.startswith("error: Couldn't find key in agent?")
        assert "fatal: failed to write commit object" in done.stderr
        assert "M  a.txt" in lab.git("status", "--short").stdout  # changes stay staged
        # a missing shim file
        missing = {**env, "GIT_CONFIG_VALUE_3": "/nonexistent/shim"}
        done = lab.git("commit", "-q", "-m", "x", env=missing)
        assert done.returncode == 128 and "cannot exec '/nonexistent/shim'" in done.stderr
        # the 2a isolation program (/usr/bin/false): git prints an empty error
        isolated = {**env, "GIT_CONFIG_VALUE_3": "/usr/bin/false"}
        done = lab.git("commit", "-q", "-m", "x", env=isolated)
        assert done.returncode == 128 and done.stderr.startswith("error: \n")
        # a dead agent and no socket at all
        os.kill(rig.pids[0], 9)
        done = lab.git("commit", "-q", "-m", "x")
        assert done.stderr.startswith("error: Couldn't get agent socket?")
        sock.unlink(missing_ok=True)
        assert lab.git("commit", "-q", "-m", "x").stderr.startswith(
            "error: Couldn't get agent socket?"
        )

    def test_tag_signing_and_verification_use_the_same_shim(self, rig: Rig, tmp_path: Path) -> None:
        _, log, _, _, env = self._setup(rig, tmp_path)
        lab = self._repo(tmp_path, env)
        lab.git("commit", "-q", "-m", "s")
        assert lab.git("tag", "-s", "t1", "-m", "tag").returncode == 0
        assert "[-U]" in self._argv(log, rig.root)[-2]
        assert lab.git("tag", "-v", "t1").returncode == 0
        assert lab.git("verify-tag", "t1").returncode == 0


@real_ssh
class TestPrecedence:
    """Order inside git's command scope: later entries win, ``-c`` beats the env entries."""

    def test_signing_entries_appended_after_the_isolation_entries_win(
        self,
        rig: Rig,
        tmp_path: Path,
    ) -> None:
        shim, _, allowed, _, sign_env = TestSigningContract._setup(rig, tmp_path)
        iso = [
            ("commit.gpgsign", "false"),
            ("gpg.format", "openpgp"),
            ("gpg.openpgp.program", "/usr/bin/false"),
            ("gpg.ssh.program", "/usr/bin/false"),
        ]
        pairs = [
            (sign_env[f"GIT_CONFIG_KEY_{i}"], sign_env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(5)
        ]
        env = counted(*iso, *pairs)
        lab = Lab(tmp_path / "lab")
        lab.base()
        (lab.repo / "a.txt").write_text("x\n")
        lab.git("add", "-A", llm=False)
        assert lab.git("config", "--get", "commit.gpgsign", env=env).stdout.strip() == "true"
        assert lab.git("config", "--get", "gpg.ssh.program", env=env).stdout.strip() == str(shim)
        assert lab.git("commit", "-q", "-m", "append wins", env=env).returncode == 0
        assert "gpgsig " in lab.git("cat-file", "commit", "HEAD").stdout
        # `-c` comes last of all: that is why the gate forbids it on these keys
        (lab.repo / "a.txt").write_text("y\n")
        lab.git("add", "-A", llm=False)
        done = lab.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "dash c", env=env)
        assert done.returncode == 0
        assert "gpgsig " not in lab.git("cat-file", "commit", "HEAD").stdout
        assert allowed.exists()


# --- 3. trailers in prepare-commit-msg ------------------------------------------------------------

TRAILER = "Co-authored-by: LLM <llm@example.invalid>"


@needs_config_hooks
class TestTrailers:
    """``git interpret-trailers --if-exists addIfDifferent`` is idempotent for every message
    source, case-insensitive on token and value, and runs even with ``--no-verify``."""

    @staticmethod
    def _lab(tmp_path: Path, trailer: str = TRAILER) -> Lab:
        lab = Lab(tmp_path / "lab")
        script = tmp_path / "trailer.sh"
        script.write_text(
            "#!/bin/sh\nexec git interpret-trailers --in-place --if-exists addIfDifferent "
            f'--trailer "{trailer}" "$1"\n'
        )
        script.chmod(0o755)
        with Path(os.environ["GIT_CONFIG_GLOBAL"]).open("a") as handle:
            handle.write(f'[hook "tr"]\n\tevent = prepare-commit-msg\n\tcommand = "{script}"\n')
        return lab

    @staticmethod
    def _count(lab: Lab, key: str = "Co-authored-by") -> int:
        out = lab.git("log", "-1", f"--format=%(trailers:key={key},valueonly)", llm=False).stdout
        return len([x for x in out.splitlines() if x.strip()])

    @staticmethod
    def _staged(lab: Lab) -> None:
        lab.base()
        (lab.repo / "a.txt").write_text("a\nx\n")
        lab.git("add", "-A", llm=False)

    def test_dash_m_and_dash_f_and_amend_add_the_trailer_once(self, tmp_path: Path) -> None:
        lab = self._lab(tmp_path)
        self._staged(lab)
        assert lab.git("commit", "-q", "-m", "subject only").returncode == 0
        message = lab.git("log", "-1", "--format=%B", llm=False).stdout
        assert message == f"subject only\n\n{TRAILER}\n\n"
        (lab.repo / "a.txt").write_text("a\ny\n")
        lab.git("add", "-A", llm=False)
        lab.git("commit", "-q", "--amend", "--no-edit")
        assert self._count(lab) == 1
        lab.git("commit", "-q", "--amend", "-m", "new subject")
        assert self._count(lab) == 1
        self._staged(lab)
        (tmp_path / "m.txt").write_text("from file\n\nbody\n")
        lab.git("commit", "-q", "-F", str(tmp_path / "m.txt"))
        assert self._count(lab) == 1

    def test_the_comparison_ignores_case_in_token_and_value(self, tmp_path: Path) -> None:
        lab = self._lab(tmp_path)
        self._staged(lab)
        lab.git("commit", "-q", "-m", "s\n\nco-authored-by: llm <LLM@example.invalid>")
        assert self._count(lab) == 1
        self._staged(lab)
        lab.git("commit", "-q", "-m", "s\n\nCo-authored-by: Someone Else <else@example.invalid>")
        assert self._count(lab) == 2  # a different co-author stays, ours is added once

    def test_signed_off_by_and_body_text_are_not_trailers_of_ours(self, tmp_path: Path) -> None:
        lab = self._lab(tmp_path)
        self._staged(lab)
        lab.git("commit", "-q", "-m", "s\n\nSigned-off-by: H <h@example.invalid>")
        assert lab.git("log", "-1", "--format=%B", llm=False).stdout.endswith(
            f"Signed-off-by: H <h@example.invalid>\n{TRAILER}\n\n"
        )
        self._staged(lab)
        lab.git("commit", "-q", "-m", "para one\n\nstill body, not a trailer block")
        assert self._count(lab) == 1

    @pytest.mark.parametrize("source", ["merge --no-ff", "cherry-pick", "revert", "squash"])
    def test_merge_family_sources_get_exactly_one_real_trailer(
        self, tmp_path: Path, source: str
    ) -> None:
        lab = self._lab(tmp_path)
        lab.branches(diverge=True)
        if source == "merge --no-ff":
            lab.git("merge", "--no-ff", "--no-edit", "feat")
        elif source == "cherry-pick":
            lab.git("cherry-pick", "feat")
        elif source == "revert":
            lab.git("revert", "--no-edit", "HEAD", env={"GIT_EDITOR": "true"})
        else:
            lab.git("merge", "--squash", "feat")
            lab.git("commit", "-q", "--no-edit")
        # the squashed message quotes feat1's own (indented) trailer: git's parser sees one
        assert self._count(lab) == 1

    def test_assisted_by_is_idempotent_and_survives_no_verify(self, tmp_path: Path) -> None:
        lab = self._lab(tmp_path, "Assisted-by: Carter")
        self._staged(lab)
        assert lab.git("commit", "-q", "--no-verify", "-m", "x").returncode == 0
        lab.git("commit", "-q", "--amend", "--no-edit", "--no-verify")
        assert self._count(lab, "Assisted-by") == 1
        self._staged(lab)
        lab.git("commit", "-q", "-m", "x\n\nassisted-by: carter")
        assert self._count(lab, "Assisted-by") == 1

    def test_an_empty_editor_message_becomes_the_trailer_alone(self, tmp_path: Path) -> None:
        """No `-m`: the hook sees an empty message file and the trailer lands on line 1, so a
        commit whose editor wrote nothing succeeds with the trailer as its subject. Humans never
        reach the hook (AD1 no-op); an agent has no editor, so this is a documented edge."""
        lab = self._lab(tmp_path)
        self._staged(lab)
        done = lab.git("commit", "-q", env={"GIT_EDITOR": "true"})
        assert done.returncode == 0
        assert lab.git("log", "-1", "--format=%s", llm=False).stdout.strip() == TRAILER


# --- 4. guard inputs: carter.* from the global scope only ------------------------------------


class TestGuardInputs:
    def _setup(self, tmp_path: Path) -> Lab:
        lab = Lab(tmp_path / "lab")
        home = Path(os.environ["HOME"])
        carter = home / ".carter"
        carter.mkdir()
        (carter / "gitconfig").write_text(
            "[carter]\n\ttier = t2\n\tllmEmail = llm@example.invalid\n"
        )
        with Path(os.environ["GIT_CONFIG_GLOBAL"]).open("a") as handle:
            handle.write(f"[include]\n\tpath = {carter / 'gitconfig'}\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        lab.repo = repo
        return lab

    @staticmethod
    def tier(lab: Lab, *pre: str, env: dict[str, str] | None = None) -> tuple[int, str]:
        done = lab.git(
            *pre, "config", "--global", "--includes", "--get", "carter.tier", env=env, llm=False
        )
        return done.returncode, done.stdout.strip()

    def test_includes_are_needed_with_global_and_the_carter_value_is_found(
        self, tmp_path: Path
    ) -> None:
        lab = self._setup(tmp_path)
        assert self.tier(lab) == (0, "t2")
        bare = lab.git("config", "--global", "--get", "carter.tier", llm=False)
        assert (bare.returncode, bare.stdout) == (1, "")  # --global alone does not follow includes

    def test_command_line_local_and_env_values_are_ignored(self, tmp_path: Path) -> None:
        lab = self._setup(tmp_path)
        assert self.tier(lab, "-c", "carter.tier=t0") == (0, "t2")
        assert self.tier(lab, env=counted(("carter.tier", "t0"))) == (0, "t2")
        assert self.tier(lab, env={"GIT_CONFIG_PARAMETERS": "'carter.tier=t0'"}) == (0, "t2")
        assert self.tier(lab, "--config-env=carter.tier=XT", env={"XT": "t0"}) == (0, "t2")
        lab.git("config", "--local", "carter.tier", "t0", llm=False)
        assert self.tier(lab) == (0, "t2")
        plain = lab.git("config", "--get", "carter.tier", llm=False).stdout.strip()
        assert plain == "t0"  # ... while a plain read would have been fooled

    def test_an_absent_key_is_rc_1_with_no_output(self, tmp_path: Path) -> None:
        lab = self._setup(tmp_path)
        done = lab.git("config", "--global", "--includes", "--get", "carter.nothing", llm=False)
        assert (done.returncode, done.stdout, done.stderr) == (1, "", "")

    def test_the_home_based_global_reads_one_file_not_both(self, tmp_path: Path) -> None:
        """Without GIT_CONFIG_GLOBAL, --global reads ~/.gitconfig if it exists and the XDG file
        only when it does not: the include line must live in the file git actually reads."""
        lab = self._setup(tmp_path)
        home = Path(os.environ["HOME"])
        shutil.copy(os.environ["GIT_CONFIG_GLOBAL"], home / ".gitconfig")
        xdg = home / ".config" / "git"
        xdg.mkdir(parents=True)
        (xdg / "config").write_text("[carter]\n\ttier = t1\n")
        env = {k: v for k, v in os.environ.items() if k != "GIT_CONFIG_GLOBAL"}
        done = subprocess.run(
            ["git", "config", "--global", "--includes", "--get-all", "carter.tier"],
            cwd=lab.repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.stdout.split() == ["t2"]  # the XDG value is not even listed
        (home / ".gitconfig").unlink()
        done = subprocess.run(
            ["git", "config", "--global", "--includes", "--get", "carter.tier"],
            cwd=lab.repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.stdout.strip() == "t1"

    def test_the_file_fallback_reads_the_carter_file_directly(self, tmp_path: Path) -> None:
        lab = self._setup(tmp_path)
        carter = Path(os.environ["HOME"]) / ".carter" / "gitconfig"
        done = lab.git(
            "config", "--file", str(carter), "--includes", "--get", "carter.tier", llm=False
        )
        assert done.stdout.strip() == "t2"


# --- 5. includeIf "gitdir:" fragments (the D64 cap mirror) --------------------------------------


class TestIncludeIfFragments:
    @staticmethod
    def _world(tmp_path: Path) -> tuple[Path, Path, Path]:
        ws = tmp_path / "ws"
        ws.mkdir()
        (tmp_path / "other").mkdir()
        frag = tmp_path / "frag-t1"
        frag.write_text("[carter]\n\ttier = t1\n")
        with Path(os.environ["GIT_CONFIG_GLOBAL"]).open("a") as handle:
            handle.write(f'[carter]\n\ttier = t2\n[includeIf "gitdir:{ws}/"]\n\tpath = {frag}\n')
        return ws, tmp_path / "other", frag

    @staticmethod
    def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "GIT_COMMITTER_NAME": "S",
            "GIT_COMMITTER_EMAIL": "s@example.invalid",
            "GIT_AUTHOR_NAME": "S",
            "GIT_AUTHOR_EMAIL": "s@example.invalid",
        }
        return subprocess.run(
            ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
        )

    def tier(self, cwd: Path) -> str:
        done = self.git(cwd, "config", "--global", "--includes", "--get", "carter.tier")
        return done.stdout.strip() or f"rc{done.returncode}"

    def repo(self, path: Path) -> Path:
        path.mkdir(parents=True)
        assert self.git(path, "init", "-q").returncode == 0
        return path

    def test_repos_and_subdirectories_under_the_workspace_get_the_fragment(
        self, tmp_path: Path
    ) -> None:
        ws, other, _ = self._world(tmp_path)
        inside = self.repo(ws / "r1")
        (inside / "src").mkdir()
        assert self.tier(inside) == self.tier(inside / "src") == "t1"
        assert self.tier(self.repo(ws / "nested" / "deep" / "r2")) == "t1"
        assert self.tier(self.repo(other / "r3")) == "t2"

    def test_a_symlinked_cwd_matches_but_a_symlinked_pattern_does_not(self, tmp_path: Path) -> None:
        """git compares the pattern with the real path of the git dir: write realpath(workspace)."""
        ws, _, frag = self._world(tmp_path)
        inside = self.repo(ws / "r1")
        link = tmp_path / "wslink"
        link.symlink_to(ws)
        assert self.tier(link / "r1") == "t1"  # cwd through a symlink
        config = Path(os.environ["GIT_CONFIG_GLOBAL"])
        config.write_text(config.read_text().replace(f"gitdir:{ws}/", f"gitdir:{link}/"))
        assert self.tier(inside) == "t2" and self.tier(link / "r1") == "t2"

    def test_the_trailing_slash_is_required_and_gitdir_i_ignores_case(self, tmp_path: Path) -> None:
        ws, _, _ = self._world(tmp_path)
        inside = self.repo(ws / "r1")
        config = Path(os.environ["GIT_CONFIG_GLOBAL"])
        original = config.read_text()
        config.write_text(original.replace(f"gitdir:{ws}/", f"gitdir:{ws}"))
        assert self.tier(inside) == "t2"
        config.write_text(original.replace("gitdir:", "gitdir/i:").replace("ws", "WS"))
        assert self.tier(inside) == "t1"

    def test_the_fragment_must_come_after_the_base_value(self, tmp_path: Path) -> None:
        ws, _, frag = self._world(tmp_path)
        inside = self.repo(ws / "r1")
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
            f'[includeIf "gitdir:{ws}/"]\n\tpath = {frag}\n[carter]\n\ttier = t2\n'
        )
        assert self.tier(inside) == "t2"  # a later base value overrides the fragment

    def test_linked_worktrees_follow_the_main_repos_git_dir(self, tmp_path: Path) -> None:
        """The 2b erratum: inside/outside is decided by the MAIN repo, not the worktree path."""
        ws, other, _ = self._world(tmp_path)
        main_in = self.repo(ws / "main-in")
        main_out = self.repo(other / "main-out")
        for repo in (main_in, main_out):
            assert self.git(repo, "commit", "-q", "--allow-empty", "-m", "i").returncode == 0
        self.git(main_in, "worktree", "add", "-q", str(ws / "wt-in-of-in"), "-b", "w1")
        self.git(main_in, "worktree", "add", "-q", str(other / "wt-out-of-in"), "-b", "w2")
        self.git(main_out, "worktree", "add", "-q", str(ws / "wt-in-of-out"), "-b", "w3")
        self.git(main_out, "worktree", "add", "-q", str(other / "wt-out-of-out"), "-b", "w4")
        assert self.tier(ws / "wt-in-of-in") == "t1"
        assert self.tier(other / "wt-out-of-in") == "t1"  # outside the workspace, still capped
        assert self.tier(ws / "wt-in-of-out") == "t2"  # inside the workspace, NOT capped: fail-open
        assert self.tier(other / "wt-out-of-out") == "t2"

    def test_a_missing_fragment_is_silent_and_a_malformed_one_breaks_all_git(
        self, tmp_path: Path
    ) -> None:
        ws, _, frag = self._world(tmp_path)
        inside = self.repo(ws / "r1")
        frag.rename(tmp_path / "gone")
        assert self.tier(inside) == "t2"  # the cap silently disappears: check --host must notice
        (tmp_path / "gone").rename(frag)
        frag.write_text("[carter\n\ttier = t1\n")
        done = self.git(inside, "status", "--short")
        assert done.returncode == 128 and "bad config line 1" in done.stderr
        frag.write_text("[carter]\n\ttier = t1\n")

    @needs_config_hooks
    def test_hooks_in_a_fragment_report_as_global_scope(self, tmp_path: Path) -> None:
        ws, _, frag = self._world(tmp_path)
        inside = self.repo(ws / "r1")
        frag.write_text(
            '[carter]\n\ttier = t1\n[hook "frag-hook"]\n\tevent = post-commit\n\tcommand = true\n'
        )
        done = self.git(inside, "hook", "list", "--show-scope", "post-commit")
        assert done.stdout.split()[:2] == ["global", "frag-hook"]


# --- 6. amend ---------------------------------------------------------------------------------


@real_ssh
class TestAmend:
    def test_amend_keeps_the_human_author_and_signs_as_the_llm(
        self,
        rig: Rig,
        tmp_path: Path,
    ) -> None:
        _, _, _, _, env = TestSigningContract._setup(rig, tmp_path)
        lab = Lab(tmp_path / "lab", extra_env=env)
        lab.base()
        human = {
            "GIT_AUTHOR_NAME": "Human Author",
            "GIT_AUTHOR_EMAIL": "human@example.invalid",
            "GIT_AUTHOR_DATE": "2020-01-02T03:04:05+0000",
            "GIT_COMMITTER_NAME": "Human Author",
            "GIT_COMMITTER_EMAIL": "human@example.invalid",
            "GIT_COMMITTER_DATE": "2020-01-02T03:04:05+0000",
        }
        (lab.repo / "a.txt").write_text("h\n")
        lab.git("add", "-A", llm=False)
        lab.git("commit", "-q", "-m", "human commit", env=human, llm=False)

        def meta() -> str:
            return lab.git(
                "log", "-1", "--format=A=%an <%ae> %ad|C=%cn <%ce>|G=%G?", "--date=iso-strict"
            ).stdout.strip()

        assert meta() == (
            "A=Human Author <human@example.invalid> 2020-01-02T03:04:05Z"
            "|C=Human Author <human@example.invalid>|G=N"
        )
        lab.git("commit", "-q", "--amend", "--no-edit")
        assert meta().startswith("A=Human Author <human@example.invalid> 2020-01-02T03:04:05Z")
        assert meta().endswith("|C=LLM Agent <llm@example.invalid>|G=G")  # K1 after the amend
        lab.git("commit", "-q", "--amend", "--no-edit", "--reset-author")
        assert meta().startswith("A=")
        assert "Human Author" not in meta().split("|")[0]  # --reset-author replaces the author
        lab.git("commit", "-q", "--amend", "--no-edit", "--date=2021-05-05T00:00:00+0000")
        assert "2021-05-05T00:00:00Z" in meta().split("|")[0]


# --- 7. the alias -------------------------------------------------------------------------------

FAKE_CARTER = (
    "#!/bin/sh\n"
    'printf "argc=%s\\n" "$#"\n'
    'for a in "$@"; do printf "[%s]\\n" "$a"; done\n'
    'printf "pwd=%s\\n" "$(pwd)"\n'
    "exit 7\n"
)


class TestAlias:
    """The RFC's alias duplicates every argument: git appends ``"$@"`` to a ``!`` alias itself."""

    @staticmethod
    def _run(tmp_path: Path, alias: str, args: list[str]) -> subprocess.CompletedProcess[str]:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "carter").write_text(FAKE_CARTER)
        (bindir / "carter").chmod(0o755)
        subprocess.run(
            ["git", "config", "--file", os.environ["GIT_CONFIG_GLOBAL"], "alias.ai-commit", alias],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "config",
                "--file",
                os.environ["GIT_CONFIG_GLOBAL"],
                "alias.commit",
                "!echo HIJACK",
            ],
            check=True,
        )
        repo = tmp_path / "repo"
        (repo / "sub dir").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        return subprocess.run(
            ["git", "ai-commit", *args],
            cwd=repo / "sub dir",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    ARGS = ["-m", 'it\'s a "quoted" $msg', "--", "weird file"]

    def test_the_rfc_alias_duplicates_the_arguments(self, tmp_path: Path) -> None:
        done = self._run(tmp_path, '!cd "${GIT_PREFIX:-.}" && carter commit "$@"', self.ARGS)
        assert done.returncode == 7
        assert done.stdout.count("[weird file]") == 2  # every argument arrives twice

    @pytest.mark.parametrize(
        "alias",
        [
            '!cd "${GIT_PREFIX:-.}" && carter commit',
            '!f() { cd "${GIT_PREFIX:-.}" && carter commit "$@"; }; f',
        ],
    )
    def test_the_working_forms_pass_the_arguments_once_from_the_subdirectory(
        self, tmp_path: Path, alias: str
    ) -> None:
        done = self._run(tmp_path, alias, self.ARGS)
        assert done.returncode == 7  # the exit code of carter comes back
        lines = done.stdout.splitlines()
        assert lines[:6] == [
            "argc=5",
            "[commit]",
            "[-m]",
            '[it\'s a "quoted" $msg]',
            "[--]",
            "[weird file]",
        ]
        assert lines[6].endswith("/repo/sub dir")  # the caller's directory, not the top level

    def test_an_alias_named_commit_is_ignored_and_a_missing_carter_is_127(
        self, tmp_path: Path
    ) -> None:
        done = self._run(tmp_path, '!cd "${GIT_PREFIX:-.}" && carter commit', [])
        assert done.returncode == 7
        repo = tmp_path / "repo"
        env = {**os.environ, "PATH": os.environ["PATH"]}
        built_in = subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "built-in wins"],
            cwd=repo,
            env={
                **env,
                "GIT_AUTHOR_NAME": "S",
                "GIT_AUTHOR_EMAIL": "s@example.invalid",
                "GIT_COMMITTER_NAME": "S",
                "GIT_COMMITTER_EMAIL": "s@example.invalid",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert built_in.returncode == 0 and "HIJACK" not in built_in.stdout
        missing = subprocess.run(
            ["git", "ai-commit"],
            cwd=repo,
            env={**os.environ, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert missing.returncode == 127 and "carter: command not found" in missing.stderr
