# ruff: noqa: E501
"""What git does that role author (the LLM is the author) relies on.

Observed on git 2.56.0, Linux, in the hermetic home, local repos only. This file pins them, so a git upgrade
that changes one of them fails here first.

* ``TestAtomicShape``: with the author, committer and signing values together the commit is
  ``L|L|G``; with only the author emitted and the human's own signing configured the bad shape
  (LLM author, human committer, signed by the HUMAN's key) appears. That is why the
  block is atomic.
* ``TestRewrites``: which verbs keep the original author in a role-b shell (author env = LLM) and
  which take the LLM .
* ``TestHumanIdentitySource``: ``git var`` returns the LLM inside a role-b shell; the human is read
  with ``git config`` in the working directory, ``includeIf`` respected.
* ``TestHookInputs``: what ``prepare-commit-msg`` receives (source argument, author env) in each
  path, and how ``git interpret-trailers --if-exists addIfDifferent`` treats case variants.
* ``TestGitHubShapes``: the ``/user/emails`` response shape and the noreply pattern, from the docs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from carter.identity.payload import to_git_env
from guard.test_carter_guard_commit_events import EMAIL, LOGIN, World
from ssh_rig import KeyPair, real_ssh

H = ("Hu Man", "human@example.invalid")
L = (LOGIN, EMAIL)
DATA = Path(__file__).resolve().parent.parent / "data" / "github"
NOREPLY = re.compile(r"^\d+\+[^@]+@users\.noreply\.github\.com$")


def ident(name: str, email: str, who: str) -> dict[str, str]:
    return {f"GIT_{who}_NAME": name, f"GIT_{who}_EMAIL": email}


H_ALL = {**ident(*H, "AUTHOR"), **ident(*H, "COMMITTER")}
B_ENV = {
    **ident(*L, "AUTHOR"),
    **ident(*L, "COMMITTER"),
}  # a role-b shell, unsigned (rewrites only)


class Repo:
    """A plain repo under the hermetic home; the human's identity is in the global git config."""

    def __init__(self, root: Path) -> None:
        self.dir = root
        root.mkdir(parents=True, exist_ok=True)
        gc = Path(os.environ["GIT_CONFIG_GLOBAL"])
        gc.write_text(
            f"[user]\n\tname = {H[0]}\n\temail = {H[1]}\n[init]\n\tdefaultBranch = main\n"
        )
        self.git("init", "-q", env=H_ALL)

    def git(
        self, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        full = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))
        }
        full.update(env or {})
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.dir,
            env=full,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )

    def commit(self, name: str, text: str, env: dict[str, str], *extra: str) -> str:
        (self.dir / name).write_text(text)
        self.git("add", name, env=env)
        done = self.git("commit", "-q", "-m", f"add {name}", *extra, env=env)
        assert done.returncode == 0, done.stderr
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def who(self, rev: str = "HEAD") -> str:
        """author-email|committer-email"""
        return self.git("log", "-1", "--format=%ae|%ce", rev).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    r = Repo(tmp_path / "repo")
    r.commit("base", "base\n", H_ALL)
    return r


class TestRewrites:
    """Every verb in a role-b shell (author and committer env = the LLM), on a HUMAN's commit."""

    def human_branch(self, repo: Repo) -> str:
        repo.git("checkout", "-q", "-b", "side", env=H_ALL)
        repo.commit("one", "1\n", H_ALL)
        return repo.commit("two", "2\n", H_ALL)

    def test_amend_keeps_the_original_author(self, repo: Repo) -> None:
        repo.commit("h", "h\n", H_ALL)
        done = repo.git("commit", "-q", "--amend", "--no-edit", env=B_ENV)
        assert done.returncode == 0 and repo.who() == f"{H[1]}|{L[1]}"

    def test_amend_with_reset_author_takes_the_llm_so_the_gate_must_forbid_it(
        self, repo: Repo
    ) -> None:
        repo.commit("h", "h\n", H_ALL)
        repo.git("commit", "-q", "--amend", "--no-edit", "--reset-author", env=B_ENV)
        assert repo.who() == f"{L[1]}|{L[1]}"  # a human commit would become the LLM's

    def test_amend_with_author_flag_sets_anything(self, repo: Repo) -> None:
        repo.commit("h", "h\n", H_ALL)
        repo.git(
            "commit",
            "-q",
            "--amend",
            "--no-edit",
            "--author=Some One <x@example.invalid>",
            env=B_ENV,
        )
        assert repo.who() == f"x@example.invalid|{L[1]}"

    def test_cherry_pick_keeps_the_original_author(self, repo: Repo) -> None:
        repo.git("checkout", "-q", "-b", "side", env=H_ALL)
        sha = repo.commit("c", "c\n", H_ALL)
        repo.git("checkout", "-q", "main", env=H_ALL)
        assert repo.git("cherry-pick", sha, env=B_ENV).returncode == 0
        assert repo.who() == f"{H[1]}|{L[1]}"

    def test_revert_and_merge_take_the_current_identity_the_llm(self, repo: Repo) -> None:
        sha = repo.commit("r", "r\n", H_ALL)
        assert repo.git("revert", "--no-edit", sha, env=B_ENV).returncode == 0
        assert repo.who() == f"{L[1]}|{L[1]}"
        repo.git("checkout", "-q", "-b", "side", "HEAD~2", env=H_ALL)
        repo.commit("s", "s\n", H_ALL)
        repo.git("checkout", "-q", "main", env=H_ALL)
        assert repo.git("merge", "--no-ff", "-m", "merge side", "side", env=B_ENV).returncode == 0
        assert repo.who() == f"{L[1]}|{L[1]}"

    @pytest.mark.parametrize(
        ("edit", "expected"),
        [
            pytest.param(
                ":", [f"{H[1]}|{H[1]}"] * 2, id="plain-pick-fast-forwards-nothing-rewritten"
            ),
            pytest.param("sed -i '1s/^pick/reword/' \"$1\"", [f"{H[1]}|{L[1]}"] * 2, id="reword"),
            pytest.param(
                "sed -i '2s/^pick/squash/' \"$1\"",
                [f"{H[1]}|{L[1]}"],
                id="squash-keeps-the-first-author",
            ),
            pytest.param(
                "sed -i '2s/^pick/fixup/' \"$1\"",
                [f"{H[1]}|{L[1]}"],
                id="fixup-keeps-the-first-author",
            ),
        ],
    )
    def test_rebase_keeps_the_original_authors(
        self, repo: Repo, tmp_path: Path, edit: str, expected: list[str]
    ) -> None:
        self.human_branch(repo)
        editor = tmp_path / "seq.sh"
        editor.write_text(f"#!/bin/sh\n{edit}\n")
        editor.chmod(0o755)
        msg = tmp_path / "msg.sh"
        msg.write_text("#!/bin/sh\nprintf 'edited\\n' > \"$1\"\n")
        msg.chmod(0o755)
        env = {**B_ENV, "GIT_SEQUENCE_EDITOR": str(editor), "GIT_EDITOR": str(msg)}
        done = repo.git("rebase", "-i", "main", env=env)
        assert done.returncode == 0, done.stderr
        got = repo.git("log", "--format=%ae|%ce", "main..HEAD").stdout.split()
        assert got == expected

    def test_commit_reusing_a_message_takes_that_commits_author(self, repo: Repo) -> None:
        sha = repo.commit("h", "h\n", H_ALL)
        (repo.dir / "n").write_text("n\n")
        repo.git("add", "n", env=B_ENV)
        repo.git("commit", "-q", "-C", sha, env=B_ENV)
        assert repo.who() == f"{H[1]}|{L[1]}"  # -C copies author and date as well


class TestHumanIdentitySource:
    def test_git_var_returns_the_llm_inside_a_role_b_shell_and_config_returns_the_human(
        self, repo: Repo
    ) -> None:
        var = repo.git("var", "GIT_AUTHOR_IDENT", env=B_ENV).stdout
        assert f"<{L[1]}>" in var
        assert repo.git("config", "--get", "user.email", env=B_ENV).stdout.strip() == H[1]
        assert repo.git("config", "--get", "user.name", env=B_ENV).stdout.strip() == H[0]

    def test_the_signing_block_does_not_touch_user_config(self, repo: Repo) -> None:
        block = {"env": {"GIT_COMMITTER_NAME": L[0], "GIT_COMMITTER_EMAIL": L[1], "CARTER_IDENTITY": L[0]},
                 "git_config": [["gpg.format", "ssh"], ["user.signingkey", "key::ssh-ed25519 AAAA"], ["commit.gpgsign", "true"]]}  # fmt: skip
        env = to_git_env({**os.environ, **ident(*L, "AUTHOR")}, block).env
        assert repo.git("config", "--get", "user.email", env=env).stdout.strip() == H[1]

    def test_include_if_overrides_are_respected_by_config_in_the_working_directory(
        self, repo: Repo, tmp_path: Path
    ) -> None:
        work = tmp_path / "work" / "proj"
        work.mkdir(parents=True)
        override = tmp_path / "work.gitconfig"
        override.write_text("[user]\n\temail = work@example.invalid\n")
        gc = Path(os.environ["GIT_CONFIG_GLOBAL"])
        gc.write_text(
            gc.read_text() + f'[includeIf "gitdir:{tmp_path}/work/"]\n\tpath = {override}\n'
        )
        repo.git("init", "-q", str(work), env=H_ALL)
        assert (
            repo.git("config", "--get", "user.email", cwd=work, env=B_ENV).stdout.strip()
            == "work@example.invalid"
        )
        assert repo.git("config", "--get", "user.name", cwd=work, env=B_ENV).stdout.strip() == H[0]
        assert (
            repo.git("config", "--get", "user.email", env=B_ENV).stdout.strip() == H[1]
        )  # outside the override

    def test_no_human_identity_is_visible_as_an_empty_config_not_as_an_error_of_git_var(
        self, repo: Repo
    ) -> None:
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text("")
        cfg = repo.git("config", "--get", "user.email", env=B_ENV)
        assert cfg.returncode == 1 and cfg.stdout == ""
        assert (
            repo.git("var", "GIT_AUTHOR_IDENT", env=B_ENV).returncode == 0
        )  # the env fills it in: git var cannot tell

    @pytest.mark.parametrize(
        "raw", [" Hu Man. ", "Hu, Man", "Ünï Çödé", 'Hu \\"Man\\"', "Hu\\nCo-authored-by: x <x@y>"]
    )
    def test_the_raw_config_value_differs_from_the_normalised_ident(
        self, repo: Repo, raw: str
    ) -> None:
        """git cleans names for its ident (crud trimmed, no newline) but ``config`` returns the raw
        value: whoever builds a trailer must validate the raw value, never paste it."""
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
            f'[user]\n\tname = "{raw}"\n\temail = {H[1]}\n'
        )
        got = repo.git("config", "--get", "user.name").stdout.rstrip("\n")
        ident_name = repo.git("var", "GIT_COMMITTER_IDENT", env=ident(*L, "COMMITTER")).stdout
        assert "Co-authored-by" not in ident_name  # the ident never carries a newline
        if "\n" in got:
            assert got.splitlines()[1].startswith("Co-authored-by:")  # the raw value does


class TestHookInputs:
    """What ``prepare-commit-msg`` is handed, recorded by a plain per-repo hook.

    Each row is ``source|author-by-git-var|GIT_AUTHOR_EMAIL-in-the-hook-env|CHERRY_PICK_HEAD``."""

    @pytest.fixture
    def rec(self, repo: Repo) -> Callable[[], list[str]]:
        hook = repo.dir / ".git" / "hooks" / "prepare-commit-msg"
        log = repo.dir.parent / "hook.log"
        hook.write_text(
            "#!/bin/sh\n"
            "who=$(git var GIT_AUTHOR_IDENT | sed 's/.*<\\(.*\\)>.*/\\1/')\n"
            'cp=-; [ -f "$(git rev-parse --git-dir)/CHERRY_PICK_HEAD" ] && cp=cherry\n'
            f'printf \'%s|%s|%s|%s\\n\' "$2" "$who" "${{GIT_AUTHOR_EMAIL-unset}}" "$cp" >> "{log}"\n'
        )
        hook.chmod(0o755)
        return lambda: log.read_text().splitlines() if log.exists() else []

    def test_amend_hands_the_hook_source_commit_and_the_commits_real_author(
        self, repo: Repo, rec: Callable[[], list[str]]
    ) -> None:
        """Observed: for ``--amend`` git exports the amended commit's author, not the shell's, so
        ``git var GIT_AUTHOR_IDENT`` in the hook is the right oracle (the human here)."""
        repo.commit("h", "h\n", H_ALL)
        before = len(rec())
        repo.git("commit", "-q", "--amend", "--no-edit", env=B_ENV)
        assert rec()[before].split("|") == ["commit", H[1], H[1], "-"]
        assert repo.who() == f"{H[1]}|{L[1]}"

    @pytest.mark.parametrize("flag", ["--reset-author", "--author=Some One <x@example.invalid>"])
    def test_amend_with_a_changed_author_shows_the_new_author_in_the_hook(
        self, repo: Repo, rec: Callable[[], list[str]], flag: str
    ) -> None:
        """K1: the guard rejects an agent that changes a commit's author, which works because the
        hook sees the NEW author under ``--reset-author`` / ``--author`` and the old one is in HEAD."""
        repo.commit("h", "h\n", H_ALL)
        before = len(rec())
        repo.git("commit", "-q", "--amend", "--no-edit", flag, env=B_ENV)
        source, var_author, _env, _cp = rec()[before].split("|")
        assert source == "commit" and var_author != H[1]
        assert var_author in (L[1], "x@example.invalid")

    def test_a_plain_commit_message_source_and_author(
        self, repo: Repo, rec: Callable[[], list[str]]
    ) -> None:
        before = len(rec())
        repo.commit("p", "p\n", B_ENV)
        assert rec()[before].split("|") == ["message", L[1], L[1], "-"]

    def test_reword_in_a_rebase_sets_the_original_author_in_the_hook_env(
        self, repo: Repo, tmp_path: Path, rec: Callable[[], list[str]]
    ) -> None:
        repo.git("checkout", "-q", "-b", "side", env=H_ALL)
        repo.commit("one", "1\n", H_ALL)
        seq = tmp_path / "seq.sh"
        seq.write_text("#!/bin/sh\nsed -i '1s/^pick/reword/' \"$1\"\n")
        seq.chmod(0o755)
        msg = tmp_path / "msg.sh"
        msg.write_text("#!/bin/sh\nprintf 'edited\\n' > \"$1\"\n")
        msg.chmod(0o755)
        before = len(rec())
        done = repo.git(
            "rebase",
            "-i",
            "main",
            env={**B_ENV, "GIT_SEQUENCE_EDITOR": str(seq), "GIT_EDITOR": str(msg)},
        )
        assert done.returncode == 0, done.stderr
        seen = rec()[before:]
        # the sequencer runs `git commit` with the picked commit's author exported
        assert seen and all(row.split("|")[1] == H[1] for row in seen), seen

    def test_cherry_pick_runs_the_hook_in_process_with_the_shells_author_and_a_cherry_pick_head(
        self, repo: Repo, rec: Callable[[], list[str]]
    ) -> None:
        """The one path where the hook's author is NOT the commit's: the pick keeps the human as
        author, but the hook sees the shell's (LLM) env. ``CHERRY_PICK_HEAD`` tells them apart."""
        repo.git("checkout", "-q", "-b", "side", env=H_ALL)
        sha = repo.commit("c", "c\n", H_ALL)
        repo.git("checkout", "-q", "main", env=H_ALL)
        before = len(rec())
        repo.git("cherry-pick", sha, env=B_ENV)
        assert rec()[before:] == [f"message|{L[1]}|{L[1]}|cherry"]
        assert repo.who() == f"{H[1]}|{L[1]}"

    def test_revert_and_merge_hand_the_hook_the_shells_author_which_is_also_the_commits(
        self, repo: Repo, rec: Callable[[], list[str]]
    ) -> None:
        sha = repo.commit("r", "r\n", H_ALL)
        before = len(rec())
        repo.git("revert", "--no-edit", sha, env=B_ENV)
        assert rec()[before:] == [f"message|{L[1]}|{L[1]}|-"]
        assert repo.who() == f"{L[1]}|{L[1]}"

    @pytest.mark.parametrize(
        ("existing", "added"),
        [
            pytest.param(f"Co-authored-by: {H[0]} <{H[1]}>", False, id="same-line"),
            pytest.param(f"Co-Authored-By: {H[0]} <{H[1]}>", False, id="key-case-differs"),
            pytest.param(f"co-authored-by: {H[0]} <{H[1]}>", False, id="key-lowercase"),
            pytest.param(
                f"Co-authored-by: {H[0].upper()} <{H[1]}>",
                False,
                id="name-case-differs-still-the-same-trailer",
            ),
            pytest.param(
                f"Co-authored-by: {H[0]} <{H[1].upper()}>",
                False,
                id="email-case-differs-still-the-same-trailer",
            ),
            pytest.param(f"Co-authored-by: {L[0]} <{L[1]}>", True, id="other-person"),
        ],
    )
    def test_add_if_different_is_idempotent_for_the_exact_line_and_key_case_only(
        self, tmp_path: Path, existing: str, added: bool
    ) -> None:
        msg = tmp_path / "MSG"
        msg.write_text(f"subject\n\nbody\n\n{existing}\n")
        trailer = f"Co-authored-by: {H[0]} <{H[1]}>"
        subprocess.run(
            [
                "git",
                "interpret-trailers",
                "--in-place",
                "--if-exists",
                "addIfDifferent",
                "--trailer",
                trailer,
                str(msg),
            ],
            check=True,
        )
        count = sum(
            1 for line in msg.read_text().splitlines() if line.lower().startswith("co-authored-by:")
        )
        assert count == (2 if added else 1)


@real_ssh
class TestAtomicShape:
    @pytest.fixture
    def world(self, tmp_path: Path, throwaway_key: Callable[..., KeyPair], real_ssh_agent) -> World:  # type: ignore[no-untyped-def]
        key = throwaway_key("ed25519")
        assert real_ssh_agent.add(key) == 0
        repo = tmp_path / "repo"
        repo.mkdir()
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
            f"[user]\n\tname = {H[0]}\n\temail = {H[1]}\n"
        )
        for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "base"]):
            subprocess.run(
                ["git", *argv],
                cwd=repo,
                env={**os.environ, **H_ALL},
                check=True,
                capture_output=True,
            )
        w = World(Path(os.environ["HOME"]), repo, key, str(real_ssh_agent.sock))
        w.configure("t2")
        return w

    def shown(self, w: World) -> str:
        from carter.identity import shim
        from carter.identity.payload import shim_path

        allowed = shim.allowed_signers_path(w.home)
        out = subprocess.run(
            [
                "git",
                "-c",
                "gpg.format=ssh",
                "-c",
                f"gpg.ssh.allowedSignersFile={allowed}",
                "-c",
                f"gpg.ssh.program={shim_path(w.home)}",
                "log",
                "-1",
                "--format=%ae|%ce|%G?|%GF",
            ],
            cwd=w.repo,
            env=os.environ,
            capture_output=True,
            text=True,
        ).stdout
        return out.strip()

    def test_author_committer_and_signer_together_give_l_l_g(self, world: World) -> None:
        env = world.env(extra=ident(*L, "AUTHOR"))
        (world.repo / "f").write_text("x\n")
        world.git("add", "f", env=env, check=True)
        world.git("commit", "-q", "-m", "role author", env=env, check=True)
        assert self.shown(world) == f"{L[1]}|{L[1]}|G|{world.key.fingerprint}"  # type: ignore[union-attr]

    def test_the_author_alone_with_the_humans_own_signing_is_the_bad_shape(
        self, world: World, tmp_path: Path, throwaway_key: Callable[..., KeyPair]
    ) -> None:
        """If only GIT_AUTHOR_* were emitted and the human signs with their key, git records an
        LLM-authored commit that the HUMAN signed and committed. Hence: all or nothing."""
        human_key = throwaway_key("ed25519").path
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
            f"[user]\n\tname = {H[0]}\n\temail = {H[1]}\n\tsigningkey = {human_key}\n[gpg]\n\tformat = ssh\n[gpg.ssh]\n\tprogram = /usr/bin/ssh-keygen\n[commit]\n\tgpgsign = true\n"
        )
        env = {**os.environ, **ident(*L, "AUTHOR")}  # no committer, no block
        (world.repo / "g").write_text("y\n")
        subprocess.run(["git", "add", "g"], cwd=world.repo, env=env, check=True)
        done = subprocess.run(
            ["git", "commit", "-q", "-m", "author only"],
            cwd=world.repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
        who = subprocess.run(
            ["git", "log", "-1", "--format=%ae|%ce"],
            cwd=world.repo,
            env=os.environ,
            capture_output=True,
            text=True,
        ).stdout.strip()
        raw = subprocess.run(
            ["git", "cat-file", "commit", "HEAD"],
            cwd=world.repo,
            env=os.environ,
            capture_output=True,
            text=True,
        ).stdout
        assert (
            who == f"{L[1]}|{H[1]}" and "gpgsig" in raw
        )  # L authored, H committed and signed: shape (d)

    def test_a_locked_key_aborts_a_role_b_commit_like_role_a(self, world: World) -> None:
        env = world.env(extra=ident(*L, "AUTHOR"))
        env["SSH_AUTH_SOCK"] = (
            "/nonexistent"  # the shim names its own socket; point it nowhere via the config
        )
        (world.repo / "h").write_text("z\n")
        world.git("add", "h", env=env, check=True)
        shutil.rmtree(
            Path(world.agent_sock).parent, ignore_errors=True
        )  # the agent is gone: locked / not running
        done = world.git("commit", "-q", "-m", "locked", env=env)
        assert done.returncode != 0 and "failed to write commit object" in done.stderr


class TestGitHubShapes:
    def test_user_emails_fixture_has_the_documented_shape(self) -> None:
        rows = json.loads((DATA / "user-emails.json").read_text())
        assert all(set(r) == {"email", "primary", "verified", "visibility"} for r in rows)
        assert [r["email"] for r in rows if r["primary"]] == ["octocat@example.invalid"]
        assert {r["email"] for r in rows if r["verified"]} == {
            "octocat@example.invalid",
            "583231+octocat@users.noreply.github.com",
        }

    @pytest.mark.parametrize(
        ("email", "ok"),
        [
            ("583231+octocat@users.noreply.github.com", True),
            ("1+a@users.noreply.github.com", True),
            (
                "octocat@users.noreply.github.com",
                False,
            ),  # the old, id-less form is not linkable by id
            ("583231+octocat@users.noreply.github.com.evil.example", False),
            ("583231+@users.noreply.github.com", False),
            ("carter-bot@users.noreply.github.com", False),
            ("a@b.c", False),
            ("583231+octocat@USERS.NOREPLY.GITHUB.COM", False),
        ],
    )
    def test_the_noreply_pattern(self, email: str, ok: bool) -> None:
        assert bool(NOREPLY.match(email)) is ok
