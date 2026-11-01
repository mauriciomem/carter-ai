"""The hermetic fixture (RFC-0007 App A T18): no test reaches the developer's real
``~/.gitconfig``, ``~/.carter`` or ``~/.config/opencode``.

The autouse fixture lives in ``conftest.py``. These tests pin what it guarantees,
so later steps can write config and run git in temp repos without a second thought.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from carter.home import carter_home
from carter.install.paths import _opencode_base

# Variables that can redirect git's author/committer or inject config.
POLLUTION_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_0",
    "GIT_CONFIG_VALUE_0",
    "CARTER_IDENTITY",
    "CARTER_IDENTITY_ROLE",
    "CARTER_IDENTITY_MODE",
)


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


class TestHomeIsIsolated:
    def test_home_is_not_the_real_home(self, real_home: Path) -> None:
        assert Path(os.environ["HOME"]).resolve() != real_home.resolve()
        assert Path.home().resolve() != real_home.resolve()

    def test_carter_home_is_under_the_fixture_home(self, real_home: Path) -> None:
        assert not _inside(carter_home(), real_home)
        assert _inside(carter_home(), Path(os.environ["HOME"]))

    def test_opencode_config_dir_is_not_the_real_one(self, real_home: Path) -> None:
        assert not _inside(_opencode_base(None), real_home)

    def test_xdg_config_home_is_under_the_fixture_home(self, real_home: Path) -> None:
        xdg = Path(os.environ["XDG_CONFIG_HOME"])
        assert _inside(xdg, Path(os.environ["HOME"]))
        assert not _inside(xdg, real_home)

    def test_fixture_home_is_not_the_per_test_tmp_path(
        self, tmp_path: Path, base_dir: Path
    ) -> None:
        # Tests that list tmp_path/base_dir must not see the fixture's files.
        assert not _inside(Path(os.environ["HOME"]), tmp_path)
        assert not _inside(Path(os.environ["HOME"]), base_dir)
        assert list(tmp_path.iterdir()) == []


class TestGitIsIsolated:
    def test_git_config_global_points_into_the_fixture_home(self, real_home: Path) -> None:
        path = Path(os.environ["GIT_CONFIG_GLOBAL"])
        assert _inside(path, Path(os.environ["HOME"]))
        assert not _inside(path, real_home)
        assert path.is_file()

    def test_system_config_is_disabled(self) -> None:
        assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"

    def test_global_user_name_is_the_fixture_value(self) -> None:
        out = subprocess.run(
            ["git", "config", "--global", "--get", "user.name"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out == "Fixture Human"

    def test_global_user_email_is_the_fixture_value(self) -> None:
        out = subprocess.run(
            ["git", "config", "--global", "--get", "user.email"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out == "fixture-human@example.invalid"

    def test_no_signing_key_is_visible(self) -> None:
        proc = subprocess.run(
            ["git", "config", "--get", "user.signingkey"], capture_output=True, text=True
        )
        assert proc.returncode == 1  # key not set
        assert proc.stdout == ""

    def test_ambient_git_identity_variables_are_cleared(self) -> None:
        leaked = [v for v in POLLUTION_VARS if v in os.environ]
        assert leaked == []

    @pytest.mark.parametrize("var", ["CARTER_IDENTITY_ROLE", "CARTER_IDENTITY_MODE"])
    def test_carter_identity_session_variables_are_cleared(self, var: str) -> None:
        # The resolver reads CARTER_IDENTITY_ROLE; a developer's shell must not leak in.
        assert var not in os.environ


class TestPollutedEnvHelper:
    def test_sets_every_pollution_variable(self, pollute_git_env) -> None:
        pollute_git_env()
        missing = [v for v in POLLUTION_VARS if v not in os.environ]
        assert missing == []

    def test_polluted_values_override_the_fixture_identity(self, pollute_git_env) -> None:
        pollute_git_env()
        proc = subprocess.run(
            ["git", "var", "GIT_COMMITTER_IDENT"], capture_output=True, text=True, check=True
        )
        assert "Polluter" in proc.stdout

    def test_pollution_is_undone_after_the_test(self) -> None:
        # Runs after the test above in file order; monkeypatch must have restored env.
        assert "GIT_COMMITTER_NAME" not in os.environ
        assert "CARTER_IDENTITY" not in os.environ

    def test_helper_accepts_an_explicit_monkeypatch(
        self, pollute_git_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pollute_git_env(monkeypatch)
        assert os.environ["GIT_AUTHOR_NAME"] == "Polluter"


class TestAmbientCarterVariablesDoNotLeak:
    """Run a nested pytest with a polluted environment: the fixture must clear it."""

    def test_polluted_shell_is_cleaned_before_the_test_body(self, tmp_path: Path) -> None:
        import sys

        probe = Path(__file__).parent / "test_hermetic.py"
        env = {
            **os.environ,
            "CARTER_IDENTITY_ROLE": "author",
            "CARTER_IDENTITY_MODE": "review",
            "CARTER_IDENTITY": "x",
        }
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"{probe}::TestGitIsIsolated::test_carter_identity_session_variables_are_cleared",
                f"{probe}::TestGitIsIsolated::test_ambient_git_identity_variables_are_cleared",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=probe.parent.parent,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
