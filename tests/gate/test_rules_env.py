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
PATTERNS = next(c for c in DATA["forbidden"] if c["id"] == "env-overrides")["items"]


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
            f"unset {name}",
            f"unset -v {name}",
        ):
            assert rule_of(form) == "env-overrides", form

    def test_env_wrapper_assignment_and_unset(self, name: str) -> None:
        for form in (
            f"env {name}=1 ls",
            f"env -u {name} ls",
            f"env -u{name} ls",
            f"env --unset={name} ls",
            f"env --unset {name} ls",
        ):
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
