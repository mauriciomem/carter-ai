"""The one subprocess entry of A+ (plan 003 step 18): a scrubbed environment, hardened git."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

import carter.aplus as aplus_pkg
from carter.aplus import run as r

APLUS = Path(aplus_pkg.__file__).parent


class TestEnvironment:
    def test_author_committer_config_and_repo_overrides_are_scrubbed(self, monkeypatch) -> None:
        for k, v in {
            "GIT_AUTHOR_NAME": "x", "GIT_COMMITTER_EMAIL": "y", "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.sshCommand", "GIT_CONFIG_VALUE_0": "evil",
            "GIT_CONFIG_PARAMETERS": "'a=b'", "GIT_DIR": "/elsewhere", "GIT_WORK_TREE": "/w",
            "CARTER_IDENTITY": "z", "EMAIL": "e@e.invalid",
        }.items():  # fmt: skip
            monkeypatch.setenv(k, v)
        env = r.clean_env()
        assert not [k for k in env if k.startswith(("GIT_AUTHOR", "GIT_COMMITTER", "CARTER_"))]
        for gone in (
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_PARAMETERS",
            "GIT_DIR",
            "EMAIL",
        ):
            assert gone not in env

    def test_the_humans_global_config_location_is_kept_and_system_config_is_off(self) -> None:
        env = r.clean_env()
        assert env["GIT_CONFIG_GLOBAL"] == os.environ["GIT_CONFIG_GLOBAL"]
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"

    def test_prompts_pagers_and_the_agent_socket_are_off(self, monkeypatch) -> None:
        monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/1/agent")
        env = r.clean_env()
        assert env["GIT_TERMINAL_PROMPT"] == "0" and env["SSH_ASKPASS_REQUIRE"] == "never"
        assert env["GIT_PAGER"] == "cat" and "SSH_AUTH_SOCK" not in env

    def test_extra_values_win_and_the_process_environment_is_untouched(self) -> None:
        before = dict(os.environ)
        assert r.clean_env(extra={"FOO": "1"})["FOO"] == "1"
        assert dict(os.environ) == before


class TestGit:
    def test_runs_with_neutralising_overrides(self, repo: Path) -> None:
        def get(key: str) -> str:
            return r.git(["config", "--get", key], repo).stdout.strip()

        assert get("core.pager") == "cat" and get("core.fsmonitor") == "false"
        assert get("core.hookspath") == r.empty_hooks_dir()
        assert get("credential.helper") == "" and get("core.askpass") == ""

    def test_the_hooks_path_is_an_empty_directory_that_exists(self, repo: Path) -> None:
        path = Path(r.empty_hooks_dir())
        assert path.is_dir() and list(path.iterdir()) == []

    def test_a_repo_hook_does_not_run_under_the_hardened_wrapper(
        self, repo: Path, tmp_path: Path
    ) -> None:
        marker = tmp_path / "ran"
        hook = repo / ".git" / "hooks" / "post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
        r.git(["checkout", "-q", "-b", "other"], repo)
        assert not marker.exists()

    def test_harden_false_skips_the_overrides(self, repo: Path) -> None:
        out = r.git(["config", "--get", "core.pager"], repo, harden=False)
        assert out.returncode == 1

    def test_extra_config_pairs_are_passed_as_dash_c(self, repo: Path) -> None:
        out = r.git(["config", "--get", "x.y"], repo, config=("x.y=z",))
        assert out.stdout.strip() == "z"

    def test_missing_binary_and_timeout_are_a_typed_error(self, tmp_path: Path) -> None:
        with pytest.raises(r.RunError, match="not found"):
            r.run([str(tmp_path / "nope")])
        with pytest.raises(r.RunError, match="timed out"):
            r.run(["sleep", "5"], timeout=0.2)

    def test_nonzero_exit_is_returned_not_raised(self, repo: Path) -> None:
        assert r.git(["rev-parse", "--verify", "nope"], repo).returncode != 0


class TestSingleChokePoint:
    def test_only_run_py_touches_subprocess(self) -> None:
        offenders = []
        for src in sorted(APLUS.glob("*.py")):
            if src.name == "run.py":
                continue
            tree = ast.parse(src.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                    a.name.split(".")[0] in {"subprocess", "pty"} for a in node.names
                ):
                    offenders.append(src.name)
                if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {
                    "subprocess",
                    "pty",
                }:
                    offenders.append(src.name)
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"system", "popen", "spawnv", "execv", "Popen"}
                ):
                    offenders.append(src.name)
        assert offenders == []

    def test_no_aplus_module_imports_click(self) -> None:
        for src in sorted(APLUS.glob("*.py")):
            tree = ast.parse(src.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                assert not [n for n in names if n.split(".")[0] == "click"], src.name
