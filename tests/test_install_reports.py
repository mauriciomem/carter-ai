"""What the install and uninstall reports say when the data is not the golden scenarios'."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from carter.install import orchestrator, paths
from carter.install.reports import _changes, render_uninstall
from carter.install.uninstall import UninstallReport, Workspace, uninstall


@pytest.fixture
def installed(base_dir: Path, fake_opencode) -> Path:
    fake_opencode()
    orchestrator.run(base_dir=base_dir, verbosity=1)
    return base_dir


@pytest.mark.parametrize(
    ("stats", "expected"),
    [
        ({"created": 8, "updated": 0, "unchanged": 0}, "new"),
        ({"created": 0, "updated": 0, "unchanged": 8}, "up to date"),
        ({"created": 0, "updated": 1, "unchanged": 7}, "1 updated"),
        ({"created": 2, "updated": 1, "unchanged": 5}, "2 new, 1 updated"),
        ({"created": 2, "updated": 0, "unchanged": 6}, "2 new"),
    ],
)
def test_the_change_note_says_what_happened_to_the_files(
    stats: dict[str, int], expected: str
) -> None:
    assert _changes(stats) == expected


def test_install_prints_the_header_the_table_and_nothing_when_quiet(
    base_dir: Path, fake_opencode, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_opencode()
    orchestrator.run(base_dir=base_dir, verbosity=0)
    assert capsys.readouterr().out == ""
    orchestrator.run(base_dir=base_dir, verbosity=1)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Carter install  v") and lines[2] == "✓ Installed"
    assert re.fullmatch(r" {4}agents +8  up to date", lines[3])


def test_install_over_an_edited_file_names_the_backup_folder_on_stderr(
    installed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skill = next((paths._opencode_base(installed) / "skills").glob("carter-*/SKILL.md"))
    skill.write_text("my edit")
    capsys.readouterr()
    orchestrator.run(base_dir=installed, verbosity=1)
    got = capsys.readouterr()
    assert re.search(r"^ +skills +\d+  1 updated$", got.out, re.MULTILINE)
    [line] = [x for x in got.err.splitlines() if x.startswith("! Replaced")]
    stamp = next(paths.backups_dir(installed).iterdir()).name
    assert line.startswith("! Replaced 1 file you had edited  (copies in ")
    assert line.endswith(f"/backups/{stamp}/)")  # one line, the folder; not each file


def test_a_run_without_an_install_record_says_edited_agents_were_not_backed_up(
    installed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths.manifest_path(installed).unlink()
    capsys.readouterr()
    uninstall(installed)
    assert "! Agents you edited were not backed up  (no install record was found)" in (
        capsys.readouterr().err
    )


def test_the_rm_hint_for_a_folder_with_a_space_is_one_quoted_absolute_path(
    tmp_path: Path, fake_opencode, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "a b"
    fake_opencode()
    orchestrator.run(base_dir=base, verbosity=1)
    (base / "carter" / "memories" / "user" / "n.md").write_text("mine")
    capsys.readouterr()
    report = uninstall(base)
    assert report.rm_all == f"rm -r '{base / 'carter'}'"
    assert report.rm_all in capsys.readouterr().out


def test_workspaces_with_different_leftovers_each_get_their_own_also_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    here = Workspace(Path("/w/a"), True, "rm /w/a/x", also=(".carter/",))
    there = Workspace(Path("/w/b"), True, "", also=(".carter/", "AGENTS.md"))
    render_uninstall(UninstallReport(workspaces=[here, there], manager="pip uninstall carter-ai"))
    out = capsys.readouterr().out
    assert "    /w/a: also yours to delete: .carter/\n" in out
    assert "    /w/b: also yours to delete: .carter/, AGENTS.md\n" in out
    assert "/w/b  no Carter agents left" in out


def test_a_second_uninstall_says_there_was_nothing_to_remove(
    installed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    uninstall(installed)
    capsys.readouterr()
    uninstall(installed)
    assert "✓ Uninstalled  nothing was left to remove" in capsys.readouterr().out
