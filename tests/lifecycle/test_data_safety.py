"""Characterization of the data-loss behaviours the lean-CLI work fixes.

Each test states the wanted behaviour and is ``xfail(strict=True)`` against today's
code; the change named in the reason removes the marker. A test that starts passing early fails
the suite (strict), so the marker cannot be forgotten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carter.install import orchestrator, paths
from carter.install.console import set_verbosity
from carter.install.uninstall import uninstall
from lifecycle.helpers import tree_diff, tree_snapshot


def _skills(base_dir: Path) -> Path:
    return paths._opencode_base(base_dir) / "skills"


def test_tree_helpers_report_added_removed_and_changed(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("a")
    (tmp_path / "edit.txt").write_text("a")
    (tmp_path / "gone.txt").write_text("a")
    before = tree_snapshot(tmp_path)
    (tmp_path / "edit.txt").write_text("b")
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "new").mkdir()
    assert tree_diff(before, tree_snapshot(tmp_path)) == "~ edit.txt\n- gone.txt\n+ new"
    assert tree_diff(before, before) == ""


def test_tree_snapshot_records_links_without_following(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("x")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside)
    assert tree_snapshot(root) == {"link": ("link", tree_snapshot(root)["link"][1], str(outside))}


def test_two_edited_skills_both_get_a_backup(installed: Path) -> None:
    edited = sorted(_skills(installed).glob("*/SKILL.md"))[:2]
    for skill in edited:
        skill.write_text("my edit of " + skill.parent.name)
    orchestrator.run(base_dir=installed, verbosity=1)
    copies = {p.read_text() for p in paths.backups_dir(installed).rglob("SKILL.md")}
    assert copies == {"my edit of " + s.parent.name for s in edited}


@pytest.mark.xfail(strict=True, reason="pending: no manifest removes only shipped names")
def test_user_skill_named_carter_something_survives_uninstall_without_manifest(
    installed: Path,
) -> None:
    mine = _skills(installed) / "carter-mine" / "SKILL.md"
    mine.parent.mkdir()
    mine.write_text("my skill\n")
    paths.manifest_path(installed).unlink()
    uninstall(installed)
    assert mine.read_text() == "my skill\n"


@pytest.mark.xfail(strict=True, reason="pending: the default output says what was removed")
def test_default_uninstall_output_lists_what_was_removed(installed: Path, capsys) -> None:
    set_verbosity(1)
    capsys.readouterr()
    uninstall(installed)
    got = capsys.readouterr()
    assert "Removed" in got.out + got.err


@pytest.mark.xfail(strict=True, reason="pending: run/ goes whole, the old guard.log is migrated")
def test_old_guard_log_is_migrated_and_run_dir_removed(installed: Path) -> None:
    carter = paths._carter_base(installed)
    (carter / "run").mkdir()
    (carter / "run" / "guard.log").write_text("2026-01-01T00:00:00Z E-GUARD-UNSIGNED abc\n")
    uninstall(installed)
    assert not (carter / "run").exists()
    assert "E-GUARD-UNSIGNED" in (carter / "state" / "audit" / "guard.log").read_text()
