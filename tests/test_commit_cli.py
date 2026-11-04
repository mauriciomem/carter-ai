# ruff: noqa: E501, F811
"""``carter commit`` and ``git ai-commit`` (plan 005 step 22; RFC-0007 §4.3).

The command passes its arguments to ``git commit`` untouched; the rules of the core are tested in
``tests/identity/test_commit.py``. Here: registration, argument fidelity, subdirectories, exit codes,
agent shells, the unlock offer, and the alias end to end.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import terminal
from carter.cli import main
from carter.commit_cli import commit_cmd
from carter.identity.errors import E_SIGN_AGENT_REFUSE, registry
from carter.identity.schema import Identity, IdentityConfig
from carter.identity.writer import write_config
from identity.test_commit import COAUTHOR, EMAIL, HUMAN, LOGIN, UID, Lab, fake, lab  # noqa: F401
from ssh_rig import real_ssh


def carter(*args: str, env: dict[str, str] | None = None, input: str | None = None):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(main, ["commit", *args], env=env, input=input, catch_exceptions=False)


def t1(home: Path) -> None:
    (home / ".carter").mkdir(exist_ok=True)
    write_config(
        IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL, name=LOGIN), state="current"
        ),
        home / ".carter" / "config.toml",
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = Path(os.environ["HOME"])
    Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
        f"[user]\n\tname = {HUMAN[0]}\n\temail = {HUMAN[1]}\n"
    )
    t1(home)
    work = tmp_path / "work"
    (work / "sub" / "deep").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True, capture_output=True)
    monkeypatch.chdir(work)
    return work


def stage(repo: Path, name: str = "f.txt", text: str = "x\n") -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)


def last(repo: Path, fmt: str = "%B") -> str:
    return subprocess.run(
        ["git", "log", "-1", f"--format={fmt}"], cwd=repo, capture_output=True, text=True
    ).stdout


class TestRegistration:
    def test_the_command_is_registered_and_help_describes_it(self) -> None:
        assert main.commands["commit"] is commit_cmd
        done = CliRunner().invoke(main, ["commit", "--help"])
        assert (
            done.exit_code == 0 and "Commit the staged changes as the LLM identity" in done.output
        )
        for flag in ("--no-verify", "--no-gpg-sign", "--signoff", "--author"):
            assert flag in done.output

    def test_it_takes_no_options_of_its_own(self) -> None:
        assert [p.name for p in commit_cmd.params] == ["help"] or not [
            p for p in commit_cmd.params if p.name != "help"
        ]


class TestFidelity:
    def test_arguments_arrive_as_typed_including_spaces_double_dash_and_empty_strings(
        self, repo: Path
    ) -> None:
        stage(repo, "a b.txt")
        stage(repo, "other.txt")
        done = carter(
            "-m",
            "two  words\twith tab",
            "--trailer",
            "Reviewed-by: R <r@e.invalid>",
            "--",
            "a b.txt",
        )
        assert done.exit_code == 0, done.output
        body = last(repo)
        assert (
            body.startswith("two  words\twith tab\n")
            and "Reviewed-by: R <r@e.invalid>" in body
            and COAUTHOR in body
        )
        assert (
            subprocess.run(
                ["git", "show", "--name-only", "--format=", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
            ).stdout.split("\n")[0]
            == "a b.txt"
        )
        empty = carter(
            "--allow-empty", "-m", "subject", "-m", ""
        )  # an empty argument is not dropped
        assert empty.exit_code == 0, empty.output

    def test_it_works_from_a_subdirectory(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stage(repo, "sub/deep/x.txt")
        monkeypatch.chdir(repo / "sub" / "deep")
        done = carter("-m", "from deep")
        assert done.exit_code == 0 and last(repo, "%s") == "from deep\n"

    def test_the_trailer_is_added_once_even_if_the_user_already_passed_it(self, repo: Path) -> None:
        stage(repo)
        assert carter("-m", "x", "--trailer", COAUTHOR).exit_code == 0
        assert last(repo).count("Co-authored-by:") == 1

    def test_nothing_staged_returns_gits_message_and_exit_code(self, repo: Path) -> None:
        stage(repo)
        subprocess.run(
            ["git", "commit", "-q", "-m", "first"], cwd=repo, check=True, capture_output=True
        )
        done = CliRunner().invoke(main, ["commit", "-m", "again"], catch_exceptions=False)
        assert done.exit_code == 1  # git's own: nothing to commit (its text goes to the terminal)

    def test_refused_flags_exit_2_and_create_nothing(self, repo: Path) -> None:
        stage(repo)
        done = carter("--no-verify", "-m", "x")
        assert done.exit_code == 2 and "does not accept --no-verify" in done.output
        assert subprocess.run(
            ["git", "rev-list", "--count", "--all"], cwd=repo, capture_output=True, text=True
        ).stdout.strip() in ("0", "")

    def test_t1_warns_on_stderr_and_commits_human_human_unsigned(self, repo: Path) -> None:
        stage(repo)
        done = carter("-S", "-m", "t1")
        assert (
            done.exit_code == 0
            and "E-COMMIT-T1" in done.output
            and "dropped a bare -S" in done.output
        )
        assert (
            last(repo, "%an <%ae>|%cn <%ce>")
            == f"{HUMAN[0]} <{HUMAN[1]}>|{HUMAN[0]} <{HUMAN[1]}>\n"
        )

    def test_a_broken_config_refuses_with_e_config(self, repo: Path) -> None:
        (Path(os.environ["HOME"]) / ".carter" / "config.toml").write_text(
            "schema = 2\n[identity\nbroken"
        )
        stage(repo)
        done = carter("-m", "x")
        assert done.exit_code == 1 and "E-CONFIG" in done.output


@real_ssh
class TestT2:
    def test_a_loaded_key_signs_in_an_agent_shell_and_never_prompts(
        self, lab: Lab, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]
        monkeypatch.chdir(lab.repo)
        done = carter("-m", "agent k1", env={"AGENT": "1", "GIT_COMMITTER_EMAIL": "evil@x"})
        assert done.exit_code == 0, done.output
        got = lab.show()
        assert (
            got["status"] == "G"
            and got["committer"] == f"{LOGIN} <{EMAIL}>"
            and got["author"] == f"{HUMAN[0]} <{HUMAN[1]}>"
        )
        assert "Unlock now?" not in done.output

    def test_a_locked_key_in_an_agent_shell_refuses_and_leaves_the_changes_staged(
        self, lab: Lab, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(lab.repo)
        done = carter("-m", "x", env={"AGENT": "1"})
        assert (
            done.exit_code == 1
            and E_SIGN_AGENT_REFUSE in done.output
            and registry()[E_SIGN_AGENT_REFUSE].message.split("[")[0].strip() in done.output
        )
        assert "A  a" in lab.git("status", "--short").stdout

    def test_a_locked_key_at_a_terminal_asks_once_and_a_no_commits_unsigned_with_the_trailer(
        self, lab: Lab, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(lab.repo)
        monkeypatch.setattr(terminal, "_isatty", lambda _s: True)
        done = carter("-m", "fallback", input="n\n")
        assert done.exit_code == 0, done.output
        assert (
            done.output.count("Unlock now?") == 1
            and "E-SIGN-HUMAN-FALLBACK" in done.output
            and "Unverified" in done.output
        )
        assert "gpgsig" not in lab.raw() and COAUTHOR in lab.show()["body"]

    def test_without_a_terminal_there_is_no_question(
        self, lab: Lab, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(lab.repo)
        done = carter("-m", "x")
        assert (
            done.exit_code == 0
            and "Unlock now?" not in done.output
            and "E-SIGN-HUMAN-FALLBACK" in done.output
        )


@real_ssh
class TestAlias:
    """`git ai-commit` is a `!`-alias to `carter commit`, installed by the optional `alias` group."""

    def test_the_alias_runs_carter_commit_from_the_typed_directory_with_the_arguments_intact(
        self, repo: Path, tmp_path: Path
    ) -> None:
        from carter.guard.alias import ALIAS_KEY, ALIAS_VALUE

        bindir = tmp_path / "bin"
        bindir.mkdir()
        seen = tmp_path / "seen"
        fake_carter = bindir / "carter"
        fake_carter.write_text(f'#!/bin/sh\nprintf "%s|" "$PWD" "$@" > {seen}\n')
        fake_carter.chmod(0o755)
        subprocess.run(["git", "config", "--global", ALIAS_KEY, ALIAS_VALUE], check=True)
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        done = subprocess.run(
            ["git", "ai-commit", "-m", "a 'quoted' \"msg\"", "--", "x y", ""],
            cwd=repo / "sub",
            env=env,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
        parts = seen.read_text().split("|")
        assert (
            parts[:6]
            == [str((repo / "sub").resolve()), "commit", "-m", "a 'quoted' \"msg\"", "--", "x y"]
            and parts[6] == ""
        )

    def test_an_agent_shell_cannot_use_the_alias_the_gate_refuses_bang_aliases(self) -> None:
        from carter.gate import check

        assert check("git ai-commit -m x").decision in (
            "deny",
            "allow",
        )  # the alias value itself is a shell escape
        assert check('git -c alias.x="!sh" x').decision == "deny"
