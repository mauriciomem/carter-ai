# ruff: noqa: E501
"""The human behind a role-b commit: validation, and reading ``git config`` ). The vector file is shared with the POSIX check in the guard script."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from carter.identity import coauthor
from carter.identity.coauthor import Human, human_identity, read_git_user, validate

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "human_identity_vectors.json").read_text()
)
LLM = VECTORS["llm_email"]
CASES = VECTORS["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_validate_answers_the_shared_vectors(case: dict) -> None:
    assert validate(case["name"], case["email"], LLM) == case["problem"]


def test_every_problem_is_exercised_by_the_vectors() -> None:
    assert {c["problem"] for c in CASES} - {""} == set(coauthor.PROBLEMS)


def test_the_fallbacks_come_from_the_rules_file_not_from_this_module() -> None:
    from carter.identity.rules import human_identity_rules

    rules = human_identity_rules()
    assert rules["fallback_emails"] == ["carter-bot@*"]
    assert rules["fallback_pairs"] == [
        ["Carter", "state@carter.invalid"]
    ]  # the PAIR, not each alone
    assert "carter-bot" not in Path(coauthor.__file__).read_text()


def test_the_trailer_is_the_name_and_email_and_only_for_a_usable_identity() -> None:
    assert Human("Hu Man", "h@e.invalid", "").trailer == "Co-authored-by: Hu Man <h@e.invalid>"
    assert Human("Hu Man", "h@e.invalid", "fallback").trailer == ""


def git_config(text: str) -> None:
    Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(text)


class TestReadGitUser:
    def test_reads_name_and_email(self, tmp_path: Path) -> None:
        git_config("[user]\n\tname = Hu Man\n\temail = h@e.invalid\n")
        assert read_git_user(tmp_path) == ("Hu Man", "h@e.invalid")

    def test_a_missing_value_is_empty(self, tmp_path: Path) -> None:
        git_config("[user]\n\tname = Hu Man\n")
        assert read_git_user(tmp_path) == ("Hu Man", "")
        git_config("")
        assert read_git_user(tmp_path) == ("", "")

    def test_the_last_value_wins_like_git(self, tmp_path: Path) -> None:
        git_config("[user]\n\temail = first@e.invalid\n\temail = second@e.invalid\n\tname = N\n")
        assert read_git_user(tmp_path)[1] == "second@e.invalid"

    def test_a_value_with_a_newline_stays_one_value_and_is_then_refused(
        self, tmp_path: Path
    ) -> None:
        git_config(
            '[user]\n\tname = "Hu\\nCo-authored-by: x <x@y.invalid>"\n\temail = h@e.invalid\n'
        )
        name, email = read_git_user(tmp_path)
        assert "\n" in name and email == "h@e.invalid"
        assert human_identity(tmp_path, LLM).problem == "bad-name"

    def test_include_if_in_the_given_directory_is_respected(self, tmp_path: Path) -> None:
        work = tmp_path / "work" / "p"
        work.mkdir(parents=True)
        other = tmp_path / "o.gitconfig"
        other.write_text("[user]\n\temail = work@e.invalid\n")
        git_config(
            f'[user]\n\tname = N\n\temail = h@e.invalid\n[includeIf "gitdir:{tmp_path}/work/"]\n\tpath = {other}\n'
        )
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        assert read_git_user(work) == ("N", "work@e.invalid")
        assert read_git_user(tmp_path) == ("N", "h@e.invalid")

    def test_git_author_variables_do_not_change_it(self, tmp_path: Path) -> None:
        git_config("[user]\n\tname = Hu Man\n\temail = h@e.invalid\n")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "LLM",
            "GIT_AUTHOR_EMAIL": LLM,
            "GIT_COMMITTER_EMAIL": LLM,
        }
        assert read_git_user(tmp_path, env) == ("Hu Man", "h@e.invalid")

    def test_a_missing_directory_or_git_is_empty_not_a_crash(self, tmp_path: Path) -> None:
        git_config("[user]\n\tname = N\n\temail = h@e.invalid\n")
        assert human_identity(tmp_path / "gone", LLM).ok  # falls back to the global config

        def no_git(*_a: object, **_k: object) -> object:
            raise FileNotFoundError("git")

        assert read_git_user(tmp_path, run=no_git) == ("", "")  # type: ignore[arg-type]

    def test_a_hung_git_is_bounded(self, tmp_path: Path) -> None:
        def slow(*_a: object, **kw: object) -> object:
            assert kw["timeout"] == coauthor.GIT_TIMEOUT
            raise subprocess.TimeoutExpired("git", 5)

        assert read_git_user(tmp_path, run=slow) == ("", "")  # type: ignore[arg-type]
