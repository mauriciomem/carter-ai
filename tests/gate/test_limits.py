"""Limits never hide a path or a command: past a cap the gate refuses, it does not truncate.

Review of plan 004 step 21 found five caps that silently ignored the tail of a command (first 64
words, 64 candidates per word, 32 brace results, 32 glob matches, 12 wrappers). Each is pinned here.
"""

from __future__ import annotations

from pathlib import Path

from carter.gate import paths
from gate.helpers import rule_of


class TestNothingIsCutOff:
    def test_a_credential_after_many_words(self) -> None:
        assert rule_of("cat " + "a " * 200 + "~/.ssh/id_rsa") == "credential-paths"

    def test_a_credential_after_many_path_pieces(self) -> None:
        assert rule_of("cat " + ":".join(["x"] * 200) + ":~/.ssh/id") == "credential-paths"

    def test_a_credential_among_many_brace_alternatives(self) -> None:
        alts = ",".join(f"a{i}" for i in range(100)) + ",ssh"
        assert rule_of("cat ~/.{" + alts + "}/id") == "credential-paths"

    def test_too_many_brace_results_are_refused(self) -> None:
        alts = ",".join(str(i) for i in range(paths.MAX_BRACE + 1))
        assert rule_of("cat ~/{" + alts + "}/x") == "gate-input"

    def test_a_credential_among_many_glob_matches(self, tmp_path: Path) -> None:
        home = Path.home()
        (home / ".ssh").mkdir(parents=True, exist_ok=True)
        for i in range(100):
            (home / f".s{i:03d}").mkdir()
        assert rule_of("cat ~/.s*/id_rsa") == "credential-paths"

    def test_a_control_file_after_many_words(self) -> None:
        assert rule_of("echo " + "a " * 200 + "> ~/.carter/isolation.json") == "control-files"

    def test_more_wrappers_than_the_cap_is_refused(self) -> None:
        assert rule_of("env " * 40 + "git push") == "dynamic-command"
        assert rule_of("env " * 3 + "git push") == "push-verbs"


class TestShellKeywordsThatHideACommand:
    def test_function_and_coproc_names_are_not_commands(self) -> None:
        assert rule_of("function f { git push; }; f") == "push-verbs"
        assert rule_of("function f() { git push; }") == "push-verbs"
        assert rule_of("coproc git push") == "push-verbs"
        assert rule_of("coproc NAME { git push; }") == "push-verbs"
        assert rule_of("coproc NAME { ls; }") is None


class TestBudget:
    def test_the_filesystem_budget_degrades_to_string_checks(self) -> None:
        words = " ".join(f"d{i}/f" for i in range(paths.FS_BUDGET + 10))
        assert rule_of("ls " + words + " ~/.ssh/id", cwd="/tmp") == "credential-paths"

    def test_work_grows_linearly_with_the_command(self) -> None:
        """A quadratic scan (``w not in list``) once made a 1 MiB command run for hours."""
        import time  # noqa: PLC0415

        started = time.perf_counter()
        assert rule_of("echo " + "a " * 60000, cwd="/tmp") is None
        assert time.perf_counter() - started < 5
