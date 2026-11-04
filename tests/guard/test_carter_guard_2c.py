# ruff: noqa: E501, F811
"""``carter-guard`` for role b: author / ``Co-authored-by`` self-consistency (plan 006 step 7;
freeze K1, K2, K3; RFC-0007 §4.1, §4.4).

The script never reads the role. At T2 the committer must be the LLM; when the commit's author is
the LLM the trailer is the human's (``git config`` in the repo), otherwise the LLM's. The same
rule runs under ``dash`` and ``bash --posix``, and the real-git flows (amend, cherry-pick, rebase,
revert, merge) run the script as git's own hook with a real signing agent.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from carter.guard import hooks
from carter.identity.errors import registry
from guard.test_carter_guard_2b import COAUTHOR, EMAIL, LOGIN, World, sh, world  # noqa: F401, F811 - fixtures
from ssh_rig import KeyPair, real_ssh

DATA = Path(__file__).resolve().parent.parent / "data" / "human_identity_vectors.json"
VECTORS = json.loads(DATA.read_text())
HUMAN = ("Hu Man", "human@example.invalid")
HUMAN_LINE = f"Co-authored-by: {HUMAN[0]} <{HUMAN[1]}>"
LLM_AUTHOR = {"GIT_AUTHOR_NAME": LOGIN, "GIT_AUTHOR_EMAIL": EMAIL}


def set_human(name: str = HUMAN[0], email: str = HUMAN[1], extra: str = "") -> None:
    lines = (
        ["[user]"]
        + ([f"\tname = {name}"] if name else [])
        + ([f"\temail = {email}"] if email else [])
    )
    Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text("\n".join(lines) + "\n" + extra)


@pytest.fixture(autouse=True)
def human() -> None:
    set_human()


class TestSharedVectors:
    """The POSIX check and ``coauthor.validate`` give the same answer on every shared case."""

    def sourced(self, tmp_path: Path) -> Path:
        text = hooks.render_script()
        head = text[: text.index("event=${1-}")]
        path = tmp_path / "functions.sh"
        path.write_text(head)
        return path

    @pytest.mark.parametrize("case", VECTORS["cases"], ids=[c["id"] for c in VECTORS["cases"]])
    def test_human_problem_answers_the_vectors(
        self, sh: list[str], tmp_path: Path, case: dict
    ) -> None:
        script = self.sourced(tmp_path)
        done = subprocess.run(
            [*sh, "-c", '. "$1"; human_problem "$2" "$3" "$4"', "x", str(script), case["name"], case["email"], VECTORS["llm_email"]],
            capture_output=True, text=True, timeout=30,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        assert done.stdout == case["problem"]

    def test_the_fallbacks_in_the_script_are_the_rules_file_values(self) -> None:
        text = hooks.render_script()
        assert (
            "human_fallback_email() { case $1 in carter-bot@*)" in text
            and "human_fallback_pair() { case $1:$2 in carter:state@carter.invalid)" in text
        )
        assert "@@" not in text


class TestRoleBHook:
    """``prepare-commit-msg`` / ``commit-msg`` called directly (no signing)."""

    def role_b(self, world: World) -> dict[str, str]:
        world.configure("t2", role="author")
        return world.env()

    def test_the_entry_gives_role_b_the_llm_as_author_so_the_hook_wants_the_humans_line(
        self, world: World, sh: list[str]
    ) -> None:
        env = self.role_b(world)
        assert env["GIT_AUTHOR_EMAIL"] == EMAIL  # the plugin's block
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert done.returncode == 0, done.stderr
        assert (world.repo / "MSG").read_text() == f"msg\n\n{HUMAN_LINE}\n"

    def test_the_line_is_added_once(self, world: World, sh: list[str]) -> None:
        env = self.role_b(world)
        world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        again = (world.repo / "MSG").read_text()
        assert world.run_hook(sh, "prepare-commit-msg", again, env).returncode == 0
        assert (world.repo / "MSG").read_text().count("Co-authored-by:") == 1

    @pytest.mark.parametrize(
        "existing",
        [HUMAN_LINE.upper(), HUMAN_LINE.lower(), f"Co-Authored-By: {HUMAN[0]} <{HUMAN[1]}>"],
    )
    def test_a_case_variant_of_the_line_is_the_same_line(
        self, world: World, sh: list[str], existing: str
    ) -> None:
        env = self.role_b(world)
        world.run_hook(sh, "prepare-commit-msg", f"msg\n\n{existing}\n", env)
        assert (world.repo / "MSG").read_text().count("o-authored-by:") + (
            world.repo / "MSG"
        ).read_text().lower().count("co-authored-by:") - (world.repo / "MSG").read_text().count(
            "o-authored-by:"
        ) == 1

    def test_the_llm_line_is_not_added_in_role_b(self, world: World, sh: list[str]) -> None:
        env = self.role_b(world)
        world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert COAUTHOR not in (world.repo / "MSG").read_text()

    def test_the_humans_own_includeif_identity_is_the_one_used(
        self, world: World, sh: list[str], tmp_path: Path
    ) -> None:
        override = tmp_path / "work.gitconfig"
        override.write_text("[user]\n\temail = work@example.invalid\n")
        set_human(extra=f'[includeIf "gitdir:{world.repo.parent}/"]\n\tpath = {override}\n')
        env = self.role_b(world)
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert done.returncode == 0, done.stderr
        assert (
            (world.repo / "MSG")
            .read_text()
            .endswith(f"Co-authored-by: {HUMAN[0]} <work@example.invalid>\n")
        )

    @pytest.mark.parametrize(
        ("name", "email", "problem"),
        [
            ("", "", "missing-name"),
            (HUMAN[0], "", "missing-email"),
            (HUMAN[0], EMAIL, "llm-email"),
            (HUMAN[0], "carter-bot@users.noreply.github.com", "fallback"),
            ("Carter", "state@carter.invalid", "fallback"),
            ("Hu\\nCo-authored-by: x <x@y.invalid>", HUMAN[1], "bad-name"),
        ],
    )
    def test_an_unusable_human_identity_rejects_with_the_registered_code_and_changes_nothing(
        self, world: World, sh: list[str], name: str, email: str, problem: str
    ) -> None:
        env = self.role_b(world)  # the plugin saw a usable identity; it changed before the hook ran
        set_human(f'"{name}"' if "\\n" in name else name, email)
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        entry = registry()["E-HUMAN-IDENTITY"]
        assert done.returncode == 1 and done.stdout == ""
        assert entry.message in done.stderr and entry.remediation in done.stderr
        assert f"human identity problem (E-HUMAN-IDENTITY): {problem}" in done.stderr
        assert (world.repo / "MSG").read_text() == "msg\n"
        assert HUMAN[1] not in done.stderr  # tokens only, never the values

    @pytest.mark.parametrize(
        ("name", "email"),
        [("Carter", "carter@example.invalid"), ("Hu Man", "state@carter.invalid")],
    )
    def test_a_person_named_carter_gets_their_line(
        self, world: World, sh: list[str], name: str, email: str
    ) -> None:
        env = self.role_b(world)
        set_human(name, email)
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert done.returncode == 0, done.stderr
        assert (world.repo / "MSG").read_text().endswith(f"Co-authored-by: {name} <{email}>\n")

    def test_a_human_author_still_gets_the_llm_line_whatever_the_humans_identity_is(
        self, world: World, sh: list[str]
    ) -> None:
        set_human("", "")
        world.configure("t2")  # role a: the author is whoever git config says
        env = world.env()
        env |= {"GIT_AUTHOR_NAME": "Someone", "GIT_AUTHOR_EMAIL": "someone@example.invalid"}
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert done.returncode == 0, done.stderr
        assert (world.repo / "MSG").read_text().endswith(f"{COAUTHOR}\n")

    def test_the_committer_must_still_be_the_llm_in_role_b(
        self, world: World, sh: list[str]
    ) -> None:
        env = self.role_b(world)
        env |= {
            "GIT_COMMITTER_NAME": "Hu Man",
            "GIT_COMMITTER_EMAIL": HUMAN[1],
        }  # an author-only block would look like this
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert (
            done.returncode == 1
            and "E-GUARD-COMMITTER" in done.stderr
            or registry()["E-GUARD-COMMITTER"].remediation in done.stderr
        )

    def test_author_without_the_signing_block_is_the_h7_shape_and_is_rejected(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2", role="author")
        done = world.run_hook(
            sh, "prepare-commit-msg", "msg\n", world.env(block=False, author_llm=True)
        )
        assert done.returncode == 1 and registry()["E-GUARD-NOIDENT"].message in done.stderr

    def test_below_t2_the_author_is_not_judged(self, world: World, sh: list[str]) -> None:
        world.configure("t1")
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", world.env(author_llm=True))
        assert done.returncode == 0 and (world.repo / "MSG").read_text().endswith(f"{COAUTHOR}\n")

    def test_commit_msg_wants_the_exact_humans_line_in_role_b(
        self, world: World, sh: list[str]
    ) -> None:
        env = self.role_b(world)
        ok = world.run_hook(sh, "commit-msg", f"msg\n\n{HUMAN_LINE}\n", env)
        assert ok.returncode == 0, ok.stderr
        upper = world.run_hook(sh, "commit-msg", f"msg\n\n{HUMAN_LINE.upper()}\n", env)
        assert upper.returncode == 0, upper.stderr
        for wrong in (
            f"msg\n\n{COAUTHOR}\n",
            "msg\n",
            "msg\n\nCo-authored-by: Other <other@example.invalid>\n",
        ):
            done = world.run_hook(sh, "commit-msg", wrong, env)
            assert (
                done.returncode == 1 and registry()["E-GUARD-TRAILER"].remediation in done.stderr
            ), wrong

    def test_commit_msg_with_an_unusable_human_rejects_not_downgrades(
        self, world: World, sh: list[str]
    ) -> None:
        env = self.role_b(world)
        set_human("", "")
        done = world.run_hook(sh, "commit-msg", f"msg\n\n{COAUTHOR}\n", env)
        assert done.returncode == 1 and registry()["E-HUMAN-IDENTITY"].message in done.stderr

    def test_commit_msg_in_role_a_wants_the_exact_llm_line(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        env = world.env()
        assert world.run_hook(sh, "commit-msg", f"msg\n\n{COAUTHOR}\n", env).returncode == 0
        done = world.run_hook(
            sh, "commit-msg", "msg\n\nCo-authored-by: someone <s@example.invalid>\n", env
        )
        assert done.returncode == 1

    def test_the_human_path_still_runs_no_git(self, world: World, sh: list[str]) -> None:
        world.configure("t2", role="author")
        env = {k: v for k, v in world.env().items() if k != "CARTER_AGENT_SHELL"}
        for k in ("AGENT", "OPENCODE", "OPENCODE_SESSION_ID", "AI_AGENT"):
            env.pop(k, None)
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert done.returncode == 0 and (world.repo / "MSG").read_text() == "msg\n"


@real_ssh
class TestRealGit:
    """The script as git's own hook, signing through a real dedicated agent (role b world)."""

    @pytest.fixture
    def rb(self, tmp_path: Path, throwaway_key: Callable[..., KeyPair], real_ssh_agent) -> World:  # type: ignore[no-untyped-def]
        key = throwaway_key("ed25519")
        assert real_ssh_agent.add(key) == 0
        repo = tmp_path / "repo"
        repo.mkdir()
        base = {
            **os.environ,
            "GIT_AUTHOR_NAME": HUMAN[0],
            "GIT_AUTHOR_EMAIL": HUMAN[1],
            "GIT_COMMITTER_NAME": HUMAN[0],
            "GIT_COMMITTER_EMAIL": HUMAN[1],
        }
        for argv in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "base"]):
            subprocess.run(["git", *argv], cwd=repo, env=base, check=True, capture_output=True)
        world = World(Path(os.environ["HOME"]), repo, key, str(real_ssh_agent.sock))
        world.configure("t2", role="author")
        world.install_repo_hooks()
        return world

    def human_commit(self, w: World, name: str, text: str) -> str:
        (w.repo / name).write_text(text)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": HUMAN[0],
            "GIT_AUTHOR_EMAIL": HUMAN[1],
            "GIT_COMMITTER_NAME": HUMAN[0],
            "GIT_COMMITTER_EMAIL": HUMAN[1],
        }
        subprocess.run(["git", "add", name], cwd=w.repo, env=env, check=True)
        done = subprocess.run(
            ["git", "commit", "-q", "-m", f"human {name}"],
            cwd=w.repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
        return self.head(w)

    def head(self, w: World) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=w.repo, env=os.environ, capture_output=True, text=True
        ).stdout.strip()

    def who(self, w: World, rev: str = "HEAD") -> str:
        return subprocess.run(
            ["git", "log", "-1", "--format=%ae|%ce", rev],
            cwd=w.repo,
            env=os.environ,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def signature(self, w: World, rev: str = "HEAD") -> str:
        from carter.identity import shim
        from carter.identity.payload import shim_path

        allowed = shim.allowed_signers_path(w.home)
        return subprocess.run(
            ["git", "-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={allowed}", "-c", f"gpg.ssh.program={shim_path(w.home)}", "log", "-1", "--format=%G?|%GF", rev],
            cwd=w.repo, env=os.environ, capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip

    def trailers(self, w: World, rev: str = "HEAD") -> list[str]:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%B", rev],
            cwd=w.repo,
            env=os.environ,
            capture_output=True,
            text=True,
        ).stdout
        return [ln for ln in out.splitlines() if ln.lower().startswith("co-authored-by:")]

    def test_a_role_b_commit_is_l_l_g_with_exactly_the_humans_line(self, rb: World) -> None:
        (rb.repo / "f").write_text("x\n")
        rb.git("add", "f", check=True)
        done = rb.git("commit", "-q", "-m", "role b")
        assert done.returncode == 0, done.stderr
        assert self.who(rb) == f"{EMAIL}|{EMAIL}"
        assert self.signature(rb) == f"G|{rb.key.fingerprint}"  # type: ignore[union-attr]
        assert self.trailers(rb) == [HUMAN_LINE]

    def test_amend_of_the_agents_own_commit_keeps_one_humans_line(self, rb: World) -> None:
        (rb.repo / "f").write_text("x\n")
        rb.git("add", "f", check=True)
        rb.git("commit", "-q", "-m", "role b", check=True)
        done = rb.git("commit", "-q", "--amend", "--no-edit")
        assert done.returncode == 0, done.stderr
        assert self.who(rb) == f"{EMAIL}|{EMAIL}" and self.trailers(rb) == [HUMAN_LINE]

    def test_amend_of_a_human_commit_keeps_the_human_as_author_and_adds_the_llm_line(
        self, rb: World
    ) -> None:
        self.human_commit(rb, "h", "h\n")
        done = rb.git("commit", "-q", "--amend", "--no-edit")
        assert done.returncode == 0, done.stderr
        assert self.who(rb) == f"{HUMAN[1]}|{EMAIL}"
        assert self.trailers(rb) == [
            COAUTHOR
        ]  # author is the human: the LLM is credited, as in role a
        assert self.signature(rb).startswith("G|")

    @pytest.mark.parametrize("flag", ["--reset-author", "--author=Some One <x@example.invalid>"])
    def test_an_agent_cannot_take_over_a_human_commit_with_an_amend(
        self, rb: World, flag: str
    ) -> None:
        sha = self.human_commit(rb, "h", "h\n")
        done = rb.git("commit", "-q", "--amend", "--no-edit", flag)
        assert done.returncode != 0
        assert (
            "may not change a commit's author" in done.stderr and "E-GUARD-COMMITTER" in done.stderr
        )
        assert self.head(rb) == sha and self.who(rb) == f"{HUMAN[1]}|{HUMAN[1]}"

    def test_an_amend_with_a_changed_author_of_an_llm_commit_is_not_judged(self, rb: World) -> None:
        (rb.repo / "f").write_text("x\n")
        rb.git("add", "f", check=True)
        rb.git("commit", "-q", "-m", "role b", check=True)
        assert rb.git("commit", "-q", "--amend", "--no-edit", "--reset-author").returncode == 0

    def test_cherry_pick_of_a_human_commit_keeps_the_author_and_gets_the_llm_line(
        self, rb: World
    ) -> None:
        rb.git("checkout", "-q", "-b", "side", check=True)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "side2"], cwd=rb.repo, env=os.environ, check=True
        )
        sha = self.human_commit(rb, "c", "c\n")
        subprocess.run(["git", "checkout", "-q", "main"], cwd=rb.repo, env=os.environ, check=True)
        done = rb.git("cherry-pick", sha)
        assert done.returncode == 0, done.stderr
        assert self.who(rb) == f"{HUMAN[1]}|{EMAIL}" and self.trailers(rb) == [COAUTHOR]

    def test_cherry_pick_of_an_llm_commit_gets_the_humans_line(self, rb: World) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "side"], cwd=rb.repo, env=os.environ, check=True
        )
        (rb.repo / "l").write_text("l\n")
        rb.git("add", "l", check=True)
        rb.git("commit", "-q", "-m", "llm work", check=True)
        sha = self.head(rb)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=rb.repo, env=os.environ, check=True)
        done = rb.git("cherry-pick", sha)
        assert done.returncode == 0, done.stderr
        assert self.who(rb) == f"{EMAIL}|{EMAIL}" and HUMAN_LINE in self.trailers(rb)

    def test_revert_and_merge_in_role_b_carry_the_humans_line(self, rb: World) -> None:
        sha = self.human_commit(rb, "r", "r\n")
        assert rb.git("revert", "--no-edit", sha).returncode == 0
        assert self.who(rb) == f"{EMAIL}|{EMAIL}" and HUMAN_LINE in self.trailers(rb)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "side", "HEAD~2"],
            cwd=rb.repo,
            env=os.environ,
            check=True,
        )
        self.human_commit(rb, "s", "s\n")
        subprocess.run(["git", "checkout", "-q", "main"], cwd=rb.repo, env=os.environ, check=True)
        done = rb.git("merge", "--no-ff", "-m", "merge side", "side")
        assert done.returncode == 0, done.stderr
        assert self.who(rb) == f"{EMAIL}|{EMAIL}" and HUMAN_LINE in self.trailers(rb)

    def test_rebase_reword_of_human_commits_keeps_their_author_and_adds_the_llm_line(
        self, rb: World, tmp_path: Path
    ) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "side"], cwd=rb.repo, env=os.environ, check=True
        )
        self.human_commit(rb, "one", "1\n")
        seq = tmp_path / "seq.sh"
        seq.write_text("#!/bin/sh\nsed -i '1s/^pick/reword/' \"$1\"\n")
        msg = tmp_path / "msg.sh"
        msg.write_text(
            '#!/bin/sh\n{ printf \'reworded\\n\\n\'; cat "$1"; } > "$1.new" && mv "$1.new" "$1"\n'
        )  # keeps the trailer last
        for f in (seq, msg):
            f.chmod(0o755)
        env = {**rb.env(), "GIT_SEQUENCE_EDITOR": str(seq), "GIT_EDITOR": str(msg)}
        done = rb.git("rebase", "-i", "--no-ff", "main", env=env)
        assert done.returncode == 0, done.stderr
        assert self.who(rb) == f"{HUMAN[1]}|{EMAIL}" and self.trailers(rb) == [COAUTHOR]

    def test_an_unusable_human_identity_aborts_the_real_commit_and_creates_nothing(
        self, rb: World
    ) -> None:
        env = rb.env()  # the plugin saw a usable identity; it changes before the commit
        set_human("", "")
        (rb.repo / "f").write_text("x\n")
        rb.git("add", "f", check=True)
        before = self.head(rb)
        done = rb.git("commit", "-q", "-m", "role b", env=env)
        assert done.returncode != 0 and registry()["E-HUMAN-IDENTITY"].message in done.stderr
        assert self.head(rb) == before
        assert rb.git("diff", "--cached", "--name-only", env={**os.environ}).stdout.split() == ["f"]


@real_ssh
class TestAmendCannotLaunderAnAuthor:
    """Plan 006 step 12 (security read of step 7): `--amend -C <commit>` takes that commit's author,
    and the hook's source argument names the reused commit, not HEAD. The rule compares the new
    author with HEAD, the commit being replaced."""

    @pytest.fixture
    def rb(self, tmp_path: Path, throwaway_key: Callable[..., KeyPair], real_ssh_agent) -> World:  # type: ignore[no-untyped-def]
        return TestRealGit.rb.__wrapped__(TestRealGit(), tmp_path, throwaway_key, real_ssh_agent)  # type: ignore[attr-defined]

    def llm_commit(self, w: World, name: str) -> str:
        (w.repo / name).write_text(name)
        w.git("add", name, check=True)
        w.git("commit", "-q", "-m", f"llm {name}", check=True)
        return TestRealGit().head(w)

    def test_amend_with_the_message_and_author_of_an_llm_commit_is_refused(self, rb: World) -> None:
        helper = TestRealGit()
        subprocess.run(
            ["git", "checkout", "-q", "-b", "side"], cwd=rb.repo, env=os.environ, check=True
        )
        llm_sha = self.llm_commit(rb, "l")
        subprocess.run(["git", "checkout", "-q", "main"], cwd=rb.repo, env=os.environ, check=True)
        human_sha = helper.human_commit(rb, "h", "h\n")
        done = rb.git("commit", "-q", "--amend", "-C", llm_sha)
        assert done.returncode != 0 and "may not change a commit's author" in done.stderr
        assert helper.head(rb) == human_sha and helper.who(rb) == f"{HUMAN[1]}|{HUMAN[1]}"

    def test_the_same_author_through_c_is_fine(self, rb: World) -> None:
        helper = TestRealGit()
        one = helper.human_commit(rb, "a", "a\n")
        helper.human_commit(rb, "b", "b\n")
        done = rb.git(
            "commit", "-q", "--amend", "-C", one
        )  # same human author: nothing changes hands
        assert done.returncode == 0, done.stderr
        assert helper.who(rb) == f"{HUMAN[1]}|{EMAIL}"

    def test_commit_c_on_an_llm_head_is_not_judged(self, rb: World) -> None:
        helper = TestRealGit()
        human_sha = helper.human_commit(rb, "h", "h\n")
        self.llm_commit(rb, "l")  # HEAD is the LLM's
        (rb.repo / "n").write_text("n")
        rb.git("add", "n", check=True)
        done = rb.git("commit", "-q", "-C", human_sha)
        assert done.returncode == 0, done.stderr
        assert helper.who(rb) == f"{HUMAN[1]}|{EMAIL}"
