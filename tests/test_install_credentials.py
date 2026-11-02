"""``check_credentials``: the installer no longer asks for an exported GITHUB_TOKEN (step 16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from carter import ghtoken
from carter.install import prereqs
from carter.install.paths import token_path

PAT = "github_pat_11AAAAAAA0PREREQSENTINEL_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH"


def run(capsys: pytest.CaptureFixture[str], base: Path) -> str:
    prereqs.check_credentials(base)
    out = capsys.readouterr()
    return out.out + out.err


def test_github_token_is_no_longer_a_required_env_var() -> None:
    assert "GITHUB_TOKEN" not in prereqs.REQUIRED_ENV_VARS
    assert "GH_TOKEN" not in prereqs.REQUIRED_ENV_VARS


def test_no_token_file_points_at_github_token_set_not_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = run(capsys, tmp_path)
    assert "carter github-token set" in out and "own terminal" in out
    assert "export GITHUB_TOKEN" not in out and "GITHUB_TOKEN" not in out


def test_an_exported_github_token_is_not_asked_for_and_not_praised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    out = run(capsys, tmp_path)
    assert "GITHUB_TOKEN" not in out


def test_a_stored_token_file_is_reported_without_its_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ghtoken.store_token(PAT, tmp_path)
    out = run(capsys, tmp_path)
    assert "GitHub read-only token" in out and "gh-read.token" in out
    assert "PREREQSENTINEL" not in out and "not found" not in out


def test_a_symlinked_token_file_does_not_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ghtoken.store_token(PAT, tmp_path)
    real = token_path(tmp_path)
    moved = tmp_path / "moved"
    real.rename(moved)
    real.symlink_to(moved)
    assert "not found" in run(capsys, tmp_path)
