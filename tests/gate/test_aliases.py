"""Git alias resolution (RFC-0007 C.4.2 rule 7; freeze G6; plan 004 step 20)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from carter.gate import aliases
from gate.helpers import rule_of


def set_alias(name: str, value: str, where: Path | None = None) -> None:
    args = ["git", "config", "alias." + name, value]
    if where is None:
        args.insert(2, "--global")
    subprocess.run(args, cwd=where, check=True, capture_output=True)


def chain(n: int, last: str = "status") -> None:
    for i in range(1, n):
        set_alias(f"a{i}", f"a{i + 1}")
    set_alias(f"a{n}", last)


class TestResolution:
    def test_an_alias_resolves_to_the_rules_of_its_target(self, tmp_path: Path) -> None:
        set_alias("pp", "push")
        set_alias("ci", "commit --no-verify")
        set_alias("aa", "add -A")
        assert rule_of("git pp", cwd=str(tmp_path)) == "push-verbs"
        assert rule_of("git ci -m x", cwd=str(tmp_path)) == "commit-flags"
        assert rule_of("git aa", cwd=str(tmp_path)) == "staging"
        set_alias("st", "status -sb")
        assert rule_of("git st", cwd=str(tmp_path)) is None

    def test_arguments_after_the_alias_are_judged_too(self, tmp_path: Path) -> None:
        set_alias("c", "commit")
        assert rule_of("git c --no-verify", cwd=str(tmp_path)) == "commit-flags"
        assert rule_of("git c -m ok", cwd=str(tmp_path)) is None

    def test_a_shell_alias_is_refused(self, tmp_path: Path) -> None:
        set_alias("sh", "!echo hi")
        set_alias("bang", "! git push")
        assert rule_of("git sh", cwd=str(tmp_path)) == "git-alias"
        assert rule_of("git bang", cwd=str(tmp_path)) == "git-alias"

    def test_an_alias_that_starts_with_options_cannot_be_resolved(self, tmp_path: Path) -> None:
        set_alias("p", "-p log")
        assert rule_of("git p", cwd=str(tmp_path)) == "git-alias"

    def test_depth_five_is_the_cap(self, tmp_path: Path) -> None:
        chain(5)
        assert rule_of("git a1", cwd=str(tmp_path)) is None
        set_alias("a5", "a6")
        set_alias("a6", "status")
        assert rule_of("git a1", cwd=str(tmp_path)) == "git-alias"

    def test_cycles_and_self_reference(self, tmp_path: Path) -> None:
        set_alias("x", "y")
        set_alias("y", "x")
        set_alias("me", "me")
        assert rule_of("git x", cwd=str(tmp_path)) == "git-alias"
        assert rule_of("git me", cwd=str(tmp_path)) == "git-alias"

    def test_an_alias_named_like_a_builtin_is_ignored_as_git_does(self, tmp_path: Path) -> None:
        set_alias("status", "push")
        set_alias("push", "status")
        assert rule_of("git status", cwd=str(tmp_path)) is None
        assert rule_of("git push", cwd=str(tmp_path)) == "push-verbs"

    def test_local_aliases_and_dash_C(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        set_alias("lp", "push", repo)
        assert rule_of("git -C r lp", cwd=str(tmp_path)) == "push-verbs"
        assert rule_of("git -C ./r lp", cwd=str(tmp_path)) == "push-verbs"
        assert rule_of(f"git -C {repo} lp") == "push-verbs"
        assert rule_of("git lp", cwd=str(tmp_path)) is None  # unknown alias there
        assert rule_of("cd r && git lp", cwd=str(tmp_path)) == "push-verbs"

    def test_dash_c_aliases_are_refused_by_the_config_rule(self, tmp_path: Path) -> None:
        assert rule_of("git -c alias.q=status q", cwd=str(tmp_path)) == "config-flags"


class TestFailureModes:
    def test_no_directory_known_fails_closed_for_non_builtins_only(self) -> None:
        assert rule_of("git frobnicate") == "git-alias"
        assert rule_of("git status") is None
        assert (
            rule_of("git -C /nonexistent frobnicate") is None
        )  # a directory is known: git itself fails

    def test_git_missing_or_failing_means_no_alias_never_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/nonexistent")
        assert rule_of("git lfs ls-files", cwd=str(tmp_path)) is None
        assert aliases.lookup(str(tmp_path), {}) == {}

    def test_a_missing_directory_means_no_aliases(self, tmp_path: Path) -> None:
        assert aliases.lookup(str(tmp_path / "gone"), {}) == {}
        assert rule_of("git lfs ls-files", cwd=str(tmp_path / "gone")) is None

    def test_a_slow_git_is_cut_off(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        slow = tmp_path / "bin"
        slow.mkdir()
        (slow / "git").write_text("#!/bin/sh\nsleep 5\n")
        (slow / "git").chmod(0o755)
        monkeypatch.setenv("PATH", f"{slow}{os.pathsep}{os.environ['PATH']}")
        assert aliases.lookup(str(tmp_path), {}) == {}

    def test_builtins_never_trigger_a_lookup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(aliases, "lookup", lambda *a, **k: calls.append("x") or {})
        for sub in (
            "status",
            "log",
            "diff",
            "commit",
            "add",
            "checkout",
            "stash",
            "fetch",
            "worktree",
        ):
            rule_of(f"git {sub}", cwd=str(tmp_path))
        assert calls == []
        rule_of("git frobnicate", cwd=str(tmp_path))
        assert calls == ["x"]
