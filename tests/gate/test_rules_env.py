"""Environment overrides."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carter.identity.rules import load_rules
from gate.helpers import rule_of

ISOLATION = list(load_rules().isolation_vars)
DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "carter/identity/g2_rules.json").read_text()
)
ENV_RULE = next(c for c in DATA["forbidden"] if c["id"] == "env-overrides")
PATTERNS = ENV_RULE["items"]
LAUNCHERS = ENV_RULE["launcher_vars"]


def sample(pattern: str) -> str:
    return pattern.replace("*", "X")


@pytest.mark.parametrize("name", [sample(p) for p in PATTERNS] + ISOLATION)
class TestEveryListedName:
    def test_prefix_assignment(self, name: str) -> None:
        assert rule_of(f"{name}=1 git status") == "env-overrides"

    def test_standalone_assignment_and_append(self, name: str) -> None:
        assert rule_of(f"{name}=1") == "env-overrides"
        assert rule_of(f"{name}+=1") == "env-overrides"

    def test_export_declare_readonly_unset(self, name: str) -> None:
        for form in (
            f"export {name}=1",
            f"export {name}",
            f"export -n {name}",
            f"declare -x {name}=1",
            f"typeset -x {name}=1",
            f"readonly {name}=1",
            f"local {name}=1",
        ):
            assert rule_of(form) == "env-overrides", form

    def test_unset_and_env_unset_except_for_launchers(self, name: str) -> None:
        expected = None if name in LAUNCHERS else "env-overrides"
        for form in (
            f"unset {name}",
            f"unset -v {name}",
            f"env -u {name} ls",
            f"env -u{name} ls",
            f"env --unset={name} ls",
            f"env --unset {name} ls",
        ):
            assert rule_of(form) == expected, form

    def test_env_wrapper_assignment(self, name: str) -> None:
        for form in (f"env {name}=1 ls", f"env -- {name}=1 ls", f"env -i -- {name}=1 ls"):
            assert rule_of(form) == "env-overrides", form

    def test_the_time_keyword_takes_prefix_assignments(self, name: str) -> None:
        for form in (f"time {name}=1 ls", f"time -p {name}=1 ls", f"{{ time {name}=1 ls; }}"):
            assert rule_of(form) == "env-overrides", form

    def test_builtins_that_store_into_a_name(self, name: str) -> None:
        for form in (
            f"read {name} <<< x",
            f"read -r {name} <<< x",
            f"printf -v {name} x",
            f"printf -v{name} x",
            f"for {name} in a b; do ls; done",
            f"select {name} in a b; do ls; done",
            f": ${{{name}:=x}}",
            f"echo ${{{name}=x}}",
            f'echo "${{{name}:=x}}"',
            f"cat <<EOF\n${{{name}:=x}}\nEOF",
        ):
            assert rule_of(form) == "env-overrides", form

    def test_a_nameref_can_write_any_name(self, name: str) -> None:
        for form in (f"declare -n r={name}", f"typeset -n r={name}", f"local -n r={name}"):
            assert rule_of(form) == "env-overrides", form

    def test_the_second_name_of_an_export_counts(self, name: str) -> None:
        assert rule_of(f"export OK=1 {name}=2") == "env-overrides"


def test_the_guard_script_config_variable_cannot_be_set_by_an_agent() -> None:
    """``CARTER_GUARD_CONFIG`` moves the unsigned-commit log; ``CARTER_*`` already covers it."""
    for form in (
        "CARTER_GUARD_CONFIG=/tmp/x git commit -m x",
        "export CARTER_GUARD_CONFIG=/tmp/x",
        "env CARTER_GUARD_CONFIG=/tmp/x git status",
    ):
        assert rule_of(form) == "env-overrides", form


# not launchers, but a host or TTY override that has no harmless value
OTHER_GH = ["GH_FORCE_TTY", "GH_HOST", "GH_REPO", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"]
BAD_VALUES = ["sudo", "/tmp/x", "less", "'cat -A'", "truee", "$X", "$(echo cat)", "c*"]


@pytest.mark.parametrize("name", LAUNCHERS)
class TestLauncherVariables:
    """git and gh run the program these name (git(1) ENVIRONMENT, gh help environment, less(1))."""

    @pytest.mark.parametrize("value", BAD_VALUES)
    def test_any_other_value_is_refused_in_every_form(self, name: str, value: str) -> None:
        for form in (
            f"{name}={value} gh pr view 1",
            f"{name}={value}",
            f"env {name}={value} git status",
            f"export {name}={value}",
            f"declare -x {name}={value}",
            f"readonly {name}={value}",
        ):
            assert rule_of(form) == "env-overrides", form

    def test_nothing_cat_true_and_colon_are_fine_in_every_form(self, name: str) -> None:
        for value in ("", "''", '""', "cat", "'cat'", '"cat"', "true", "':'", ":"):
            for form in (
                f"{name}={value} git log",
                f"{name}={value}",
                f"env {name}={value} gh pr view 1",
                f"export {name}={value}",
                f"declare -x {name}={value}",
                f"typeset -x {name}={value}",
            ):
                assert rule_of(form) is None, form

    def test_append_and_a_bare_export_are_refused(self, name: str) -> None:
        for form in (f"{name}+=cat", f"export {name}+=cat", f"export {name}", f"export -n {name}"):
            assert rule_of(form) == "env-overrides", form

    def test_unsetting_a_launcher_is_harmless(self, name: str) -> None:
        for form in (f"unset {name}", f"unset -v {name}", f"env -u {name} git log"):
            assert rule_of(form) is None, form

    def test_the_non_assignment_builtins_never_pass(self, name: str) -> None:
        """``read`` and ``printf -v`` take the value from input; no launcher value is literal."""
        for form in (f"read {name} <<< true", f"printf -v {name} cat", f": ${{{name}:=cat}}"):
            assert rule_of(form) == "env-overrides", form

    def test_the_second_assignment_counts(self, name: str) -> None:
        assert rule_of(f"{name}=cat OK=1 {name}=sudo git log") == "env-overrides"
        assert rule_of(f"export {name}=cat {name}=sudo") == "env-overrides"


@pytest.mark.parametrize("name", OTHER_GH)
def test_host_and_tty_overrides_have_no_allowed_value(name: str) -> None:
    for form in (f"{name}=1 gh pr view 1", f"{name}= gh pr view 1", f"{name}=cat gh pr view 1"):
        assert rule_of(form) == "env-overrides", form
    assert rule_of(f"export {name}=cat") == "env-overrides"


class TestLauncherData:
    def test_launchers_are_listed_names_and_the_values_are_the_no_op_programs(self) -> None:
        assert set(LAUNCHERS) <= set(PATTERNS)
        assert set(OTHER_GH) <= set(PATTERNS)
        assert ENV_RULE["launcher_values"] == ["", "cat", "true", ":"]

    def test_the_review_vectors(self) -> None:
        """The confirmed bypasses of the gh security review and their git twins."""
        for cmd in (
            "GH_BROWSER=sudo gh pr view 1 --web",
            "BROWSER=sudo gh pr view 1 -w",
            "env GH_BROWSER=sudo gh pr view 1 --web",
            "export GH_BROWSER=sudo",
            "GH_PAGER=sudo GH_FORCE_TTY=1 gh pr view 1",
            "GIT_EXTERNAL_DIFF=sudo git diff",
            "GIT_PAGER='docker run x' git log",
            "GIT_EDITOR=sudo git commit",
            "GIT_SEQUENCE_EDITOR=sudo git rebase -i HEAD~2",
            "LESSOPEN='|-sudo %s' GH_PAGER=less gh pr view 1",
        ):
            assert rule_of(cmd) == "env-overrides", cmd
        for cmd in ("GIT_PAGER=cat git log", "GH_PAGER= gh pr view 1", "PAGER=cat gh pr diff 1"):
            assert rule_of(cmd) is None, cmd

    def test_the_remaining_ways_to_set_a_launcher(self) -> None:
        for cmd in (
            "env -- GH_BROWSER=sudo gh pr view 1 --web",
            "env -i -- GIT_EXTERNAL_DIFF=sudo git diff",
            "time GH_BROWSER=sudo gh pr view 1 --web",
            "time -p GH_BROWSER=sudo gh pr view 1 --web",
            "{ time GH_BROWSER=sudo gh pr view 1 --web; }",
            "x=GH_BROWSER; export $x=sudo; gh pr view 1 --web",
            "x=GH_BROWSER; export ${x}=sudo; gh pr view 1 --web",
            "export $(echo GH_BROWSER)=sudo",
            "declare -n r=GH_BROWSER; export r=sudo; gh pr view 1 --web",
            "declare -n r; r=GH_BROWSER",
            "read EDITOR <<< sudo; git commit",
            "printf -v EDITOR sudo; git commit",
            "set -a; read GH_BROWSER <<< sudo; gh pr view 1 --web",
            "set -a; : ${GH_BROWSER:=sudo}; gh pr view 1 --web",
            "set -a; for GH_BROWSER in sudo; do gh pr view 1 --web; done",
        ):
            assert rule_of(cmd) == "env-overrides", cmd

    def test_no_op_launchers_make_the_non_interactive_git_idioms_work(self) -> None:
        for cmd in (
            "GIT_EDITOR=true git rebase --continue",
            "GIT_EDITOR=: git commit --amend",
            "GIT_SEQUENCE_EDITOR=: git rebase -i HEAD~3",
            "GIT_SEQUENCE_EDITOR=true GIT_EDITOR=true git rebase -i HEAD~3",
            "EDITOR=true git commit --amend",
            "export GIT_EDITOR=true",
            "unset PAGER",
            "env -u PAGER -u GH_PAGER git log",
        ):
            assert rule_of(cmd) is None, cmd

    def test_unsetting_a_protected_name_is_still_refused(self) -> None:
        for cmd in ("unset GIT_DIR", "unset HOME", "env -u CARTER_X ls", "unset GH_HOST"):
            assert rule_of(cmd) == "env-overrides", cmd

    def test_plain_reads_and_loops_are_fine(self) -> None:
        for cmd in (
            "read -r line <<< x",
            "printf -v msg '%s' x",
            "for f in a b; do ls $f; done",
            "echo ${msg:=x}",
            "printf '%s\\n' -v",
            "declare -a list=(a b)",
            "local -r n=1",
        ):
            assert rule_of(cmd) is None, cmd

    @pytest.mark.parametrize(
        "form", ["export GIT_DIR+=x", "declare -x HOME+=x", "export GH_TOKEN+=x"]
    )
    def test_plus_equals_after_export_is_refused(self, form: str) -> None:
        assert rule_of(form) == "env-overrides"


class TestReadingIsFine:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo $HOME",
            'echo "$GIT_DIR"',
            "echo ${XDG_CONFIG_HOME}",
            "printenv AGENT",
            "env",
            "env | grep GIT_",
            "echo AGENT=1",
            "ls HOME=1x",
        ],
    )
    def test_reads(self, cmd: str) -> None:
        assert rule_of(cmd) is None

    @pytest.mark.parametrize(
        "cmd",
        [
            "FOO=1 ls",
            "export FOO=1 BAR=2",
            "unset FOO",
            "env FOO=1 ls",
            "env -u FOO ls",
            "PATH=/x ls",
            "GIT_TRACE=1 git status",
            "PYTHONPATH=. python3 x.py",
            "LANG=C ls",
            "CI=1 make",
        ],
    )
    def test_other_names_are_fine(self, cmd: str) -> None:
        assert rule_of(cmd) is None

    def test_the_list_is_the_data_file_plus_isolation_vars(self) -> None:
        assert "GIT_CONFIG_PARAMETERS" in ISOLATION and "GH_TOKEN" in ISOLATION
        assert rule_of("GIT_TRACE_X=1 ls") is None  # not matched by GIT_AUTHOR_* & co
