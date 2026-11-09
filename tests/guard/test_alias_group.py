# ruff: noqa: E501
"""The optional ``alias`` group: ``git ai-commit``.

A bare ``--yes`` never installs it, ``--only alias`` or a terminal yes does, and a terminal's
default is No. The alias is written to ``~/.carter/gitconfig`` only when the user has no
``alias.ai-commit`` of their own, and its value has no ``"$@"`` (git appends the arguments).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from carter.cli import main
from carter.guard import mirror_io
from carter.guard.alias import ALIAS_KEY, ALIAS_VALUE, plan_alias
from carter.guard.state import load
from carter.install.paths import carter_gitconfig_path, guard_state_path
from guard.helpers import debug_config, verbose


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


def git(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    return subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True
    )


def carter_entries() -> dict[str, str]:
    return dict(mirror_io.read_entries(carter_gitconfig_path(None)))


def global_cfg() -> Path:
    return Path(os.environ["GIT_CONFIG_GLOBAL"])


class TestConsent:
    def test_a_bare_yes_does_not_install_the_alias_and_says_so(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert "`alias` is optional and was not installed" in res.output
        assert ALIAS_KEY not in carter_entries()
        assert "alias" not in load(guard_state_path(None)).consents  # undecided, not declined

    def test_only_alias_installs_exactly_that_key(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes", "--only", "alias")
        assert res.exit_code == 0, res.output
        assert carter_entries() == {ALIAS_KEY: ALIAS_VALUE}
        assert load(guard_state_path(None)).consents["alias"]["decision"] == "accepted"
        assert (
            git("config", "--global", "--includes", "--get", ALIAS_KEY).stdout.strip()
            == ALIAS_VALUE
        )

    def test_naming_it_makes_the_one_question_about_it(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", "--only", "alias", input="n\n")  # Y/n, and no is no
        assert "Install? [Y/n]" in res.output and "Nothing installed" in res.output
        assert ALIAS_KEY not in carter_entries()
        assert (
            "alias" not in load(guard_state_path(None)).consents
            if guard_state_path(None).exists()
            else True
        )
        assert guard("install", "--only", "alias", input="\n").exit_code == 0  # Enter is yes
        assert carter_entries()[ALIAS_KEY] == ALIAS_VALUE

    def test_a_terminal_yes_installs_it(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", "--only", "alias", input="y\n")
        assert res.exit_code == 0, res.output
        assert carter_entries()[ALIAS_KEY] == ALIAS_VALUE

    def test_the_dry_run_says_it_is_optional(self, stack) -> None:
        stack.fake()
        out = guard("install", "--dry-run").output
        assert "alias              optional, not part of --yes" in out


class TestValue:
    def test_the_value_passes_no_arguments_twice(self) -> None:
        assert ALIAS_VALUE == '!cd "${GIT_PREFIX:-.}" && carter commit'
        assert '"$@"' not in ALIAS_VALUE

    def test_git_appends_the_arguments_once_and_runs_from_where_the_user_typed(
        self, stack, tmp_path: Path
    ) -> None:
        stack.fake()
        guard("install", "--yes", "--only", "alias")
        bindir = Path(os.environ["PATH"].split(":")[0])
        seen = tmp_path / "seen"
        fake = bindir / "carter"
        fake.write_text(f'#!/bin/sh\nprintf "%s|" "$PWD" "$@" > {seen}\n')
        fake.chmod(0o755)
        repo = tmp_path / "repo"
        git("init", "-q", str(repo))
        (repo / "sub").mkdir()
        done = git("ai-commit", "-m", "two words", "--", "a b", cwd=repo / "sub")
        assert done.returncode == 0, done.stderr
        got = seen.read_text().split("|")
        assert got[:5] == [str((repo / "sub").resolve()), "commit", "-m", "two words", "--"]
        assert got[5] == "a b"


class TestUserOwnedAlias:
    def test_a_users_alias_wins_and_the_snippet_is_printed(self, stack) -> None:
        git("config", "--global", ALIAS_KEY, "!echo mine")
        stack.fake()
        res = guard("install", "--yes", "--only", "alias")
        assert res.exit_code == 0, res.output
        assert "alias.ai-commit is already set in your git config; Carter kept it" in res.output
        assert (
            git("config", "--global", "--includes", "--get", ALIAS_KEY).stdout.strip()
            == "!echo mine"
        )
        assert ALIAS_KEY not in carter_entries()

    def test_carters_own_value_read_back_through_the_include_is_ours(self, stack) -> None:
        stack.fake()
        guard("install", "--yes", "--only", "alias")
        assert plan_alias(global_cfg()).status == "ours"
        stack.fake(before=debug_config(stack.live))
        again = guard("install", "--yes", "--only", "alias")
        assert "kept it" not in again.output  # not mistaken for the user's own
        assert carter_entries() == {ALIAS_KEY: ALIAS_VALUE}

    def test_a_different_value_of_the_users_is_theirs(self, tmp_path: Path) -> None:
        cfg = tmp_path / "gc"
        cfg.write_text("[alias]\n\tai-commit = !echo mine\n")
        plan = plan_alias(cfg)
        assert plan.status == "kept-user-value" and "chain" in plan.snippet


class TestRemove:
    def test_only_alias_leaves_the_hooks(self, stack) -> None:
        stack.fake()
        guard("install", "--yes", "--only", "hooks,alias")
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("remove", "--yes", "--only", "alias")
        assert res.exit_code == 0, res.output
        entries = carter_entries()
        assert ALIAS_KEY not in entries and "hook.carter-guard-post-commit.event" in entries

    def test_only_hooks_leaves_the_alias(self, stack) -> None:
        stack.fake()
        guard("install", "--yes", "--only", "hooks,alias")
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("remove", "--yes", "--only", "hooks")
        assert res.exit_code == 0, res.output
        assert carter_entries() == {ALIAS_KEY: ALIAS_VALUE}
        assert str(carter_gitconfig_path(None)) in global_cfg().read_text()

    def test_removing_both_removes_the_file_and_the_include_line(self, stack) -> None:
        before = global_cfg().read_bytes()
        stack.fake()
        guard("install", "--yes", "--only", "hooks,alias")
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert not carter_gitconfig_path(None).exists() and global_cfg().read_bytes() == before
