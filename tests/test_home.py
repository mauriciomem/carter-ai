"""``remember_workspace``: the record ``uninstall`` reads to say where Carter left files."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.home import carter_home, remember_workspace, tilde


def _file() -> Path:
    return carter_home() / "workspaces"


def test_a_path_is_written_once_one_per_line(tmp_path: Path) -> None:
    remember_workspace(tmp_path / "a")
    remember_workspace(tmp_path / "b")
    remember_workspace(tmp_path / "a")
    assert _file().read_text().splitlines() == [str(tmp_path / "a"), str(tmp_path / "b")]


def test_the_path_is_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    remember_workspace("proj/../proj")
    assert _file().read_text() == f"{tmp_path / 'proj'}\n"


def test_the_file_is_0600_even_if_it_existed_wider(tmp_path: Path) -> None:
    remember_workspace(tmp_path)
    assert stat.S_IMODE(_file().stat().st_mode) == 0o600
    _file().chmod(0o644)
    remember_workspace(tmp_path / "other")
    assert stat.S_IMODE(_file().stat().st_mode) == 0o600


def test_a_file_without_a_final_newline_does_not_merge_two_paths(tmp_path: Path) -> None:
    _file().parent.mkdir(parents=True)
    _file().write_text("/old")
    remember_workspace(tmp_path)
    assert _file().read_text().splitlines() == ["/old", str(tmp_path)]


@pytest.mark.parametrize("name", ["a\nb", "a\rb", "a\x1b[31mb", "a\x00b", "a\tb"])
def test_a_path_with_a_control_character_is_never_written(tmp_path: Path, name: str) -> None:
    remember_workspace(tmp_path / name)
    assert not _file().exists()


def test_spaces_and_quotes_are_fine(tmp_path: Path) -> None:
    remember_workspace(tmp_path / "my 'proj' $HOME")
    assert _file().read_text() == f"{tmp_path}/my 'proj' $HOME\n"


def test_an_unwritable_home_is_swallowed(tmp_path: Path) -> None:
    carter_home().parent.mkdir(parents=True, exist_ok=True)
    carter_home().write_text("a file where the directory should be")
    remember_workspace(tmp_path)  # must not raise
    assert carter_home().read_text() == "a file where the directory should be"


def test_a_file_that_is_not_utf8_is_swallowed_and_left_alone(tmp_path: Path) -> None:
    _file().parent.mkdir(parents=True)
    _file().write_bytes(b"\xff\xfe\x00")
    remember_workspace(tmp_path)
    assert _file().read_bytes() == b"\xff\xfe\x00"


def test_a_symlink_in_its_place_is_not_followed_nor_its_mode_changed(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_text("keep")
    victim.chmod(0o755)  # a guard script, say: a chmod through the link would strip this
    _file().parent.mkdir(parents=True)
    _file().symlink_to(victim)
    remember_workspace(tmp_path)
    assert victim.read_text() == "keep"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o755


def test_a_fifo_in_its_place_is_left_alone_and_does_not_hang(tmp_path: Path) -> None:
    _file().parent.mkdir(parents=True)
    os.mkfifo(_file())
    remember_workspace(tmp_path)
    assert stat.S_ISFIFO(_file().lstat().st_mode)


def test_tilde_shortens_only_a_leading_home() -> None:
    home = str(Path.home())
    assert tilde(Path(home) / ".carter") == "~/.carter"
    assert tilde(home) == "~"
    assert tilde(f"{home}2/x") == f"{home}2/x"  # another user's home that starts the same way
    assert tilde(f"/srv{home}/x") == f"/srv{home}/x"  # a copy of it elsewhere


class TestCommands:
    """``init`` records the workspace; ``update`` records one made before the record existed."""

    def _init(self, target: Path) -> None:
        res = CliRunner().invoke(main, ["init", "--single", "--no-git-state", str(target)])
        assert res.exit_code == 0, res.output

    def test_init_records_the_resolved_directory(self, tmp_path: Path) -> None:
        ws = tmp_path / "proj"
        ws.mkdir()
        self._init(ws)
        assert _file().read_text() == f"{ws.resolve()}\n"

    def test_update_records_an_older_workspace_once(self, tmp_path: Path) -> None:
        ws = tmp_path / "proj"
        ws.mkdir()
        self._init(ws)
        _file().unlink()  # a workspace made before the record existed
        for _ in range(2):
            res = CliRunner().invoke(main, ["update", str(ws)])
            assert res.exit_code == 0, res.output
        assert _file().read_text() == f"{ws.resolve()}\n"

    def test_update_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        ws = tmp_path / "proj"
        ws.mkdir()
        self._init(ws)
        _file().unlink()
        assert CliRunner().invoke(main, ["update", "--dry-run", str(ws)]).exit_code == 0
        assert not _file().exists()

    def test_a_failure_to_record_does_not_fail_init(self, tmp_path: Path) -> None:
        carter_home().write_text("in the way")
        ws = tmp_path / "proj"
        ws.mkdir()
        self._init(ws)
        assert os.path.exists(ws / ".carter" / "carter.yaml")
