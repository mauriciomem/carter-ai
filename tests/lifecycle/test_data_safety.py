"""Characterization of the data-loss behaviours the lean-CLI work fixes.

Each test states the wanted behaviour of the install -> uninstall lifecycle.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from carter.cli import main
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


def test_user_skill_named_carter_something_survives_uninstall_without_manifest(
    installed: Path,
) -> None:
    mine = _skills(installed) / "carter-mine" / "SKILL.md"
    mine.parent.mkdir()
    mine.write_text("my skill\n")
    paths.manifest_path(installed).unlink()
    uninstall(installed)
    assert mine.read_text() == "my skill\n"


def test_default_uninstall_output_lists_what_was_removed(installed: Path, capsys) -> None:
    set_verbosity(1)
    capsys.readouterr()
    uninstall(installed)
    got = capsys.readouterr()
    assert "✓ Removed\n" in got.out and "    agents " in got.out


def test_old_guard_log_is_migrated_and_run_dir_removed(installed: Path) -> None:
    carter = paths._carter_base(installed)
    (carter / "run").mkdir()
    (carter / "run" / "guard.log").write_text("2026-01-01T00:00:00Z E-GUARD-UNSIGNED abc\n")
    uninstall(installed)
    assert not (carter / "run").exists()
    assert "E-GUARD-UNSIGNED" in (carter / "state" / "audit" / "guard.log").read_text()


def test_dash_v_lists_every_file_removed_and_kept(installed: Path) -> None:
    oc = paths._opencode_base(installed)
    kept = next((oc / "skills").glob("carter-*/SKILL.md"))
    kept.write_text(kept.read_text() + "\nmine\n")
    args = ["uninstall", "--base-dir", str(installed)]
    out = CliRunner().invoke(main, [*args, "-v"]).output
    assert f"Removed {oc / 'agents' / 'carter-pm.md'}" in out
    assert f"Kept {kept}: edited since install" in out


def test_an_edited_global_agent_is_removed_with_a_copy_at_its_mirrored_path(
    installed: Path,
) -> None:
    agent = paths._opencode_base(installed) / "agents" / "carter-pm.md"
    agent.write_text("# my pm\n")
    report = uninstall(installed)
    assert not agent.exists()
    [(removed, copy)] = report.edited_copies
    assert removed == agent and copy.read_text() == "# my pm\n"
    # backups/<stamp>/<the file's own path>
    assert copy.relative_to(paths.backups_dir(installed)).parts[1:] == agent.relative_to("/").parts


def test_uninstall_touches_nothing_it_did_not_install(installed: Path) -> None:
    carter, oc = paths._carter_base(installed), paths._opencode_base(installed)
    mine = [
        carter / "memories" / "user" / "me.md",
        carter / "secrets" / "gh-read.token",
        carter / "state" / "audit" / "ops.log",
        oc / "skills" / "carter-mine" / "SKILL.md",
        oc / "agents" / "my-agent.md",
        oc / "opencode.json",
        installed / "elsewhere.txt",
    ]
    for f in mine:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("mine " + f.name)
    paths.manifest_path(installed).unlink()  # the hardest case: only names decide
    before = tree_snapshot(installed)
    uninstall(installed)
    changes = tree_diff(before, tree_snapshot(installed)).splitlines()
    assert changes and all(line.startswith("- ") for line in changes)  # only removals
    for f in mine:
        assert f.read_text() == "mine " + f.name
