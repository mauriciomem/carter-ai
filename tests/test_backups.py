"""Backups under ``backups/<UTC stamp>/``: mirrored paths, own output not copied, pruning."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from carter.install import backups, components, orchestrator, paths
from carter.install.files import _backup_file, _install_file, _mirror, _sha256

NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)


def _stamp(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime(backups.STAMP_FORMAT)


class TestMirror:
    def test_path_under_home_is_relative_to_it(self) -> None:
        assert _mirror(Path.home() / ".config" / "opencode" / "x.md") == Path(
            ".config/opencode/x.md"
        )

    def test_path_outside_home_loses_only_the_anchor(self) -> None:
        assert _mirror(Path("/srv/data/x.md")) == Path("srv/data/x.md")

    def test_dotdot_cannot_climb_out_of_the_backup_root(self, tmp_path: Path) -> None:
        source = tmp_path / "a" / ".." / ".." / "etc" / "passwd"
        root = tmp_path / "bk"
        assert not _mirror(source).is_absolute()
        assert ".." not in _mirror(source).parts
        assert (root / _mirror(source)).resolve().is_relative_to(root.resolve())

    def test_two_files_with_one_name_get_two_destinations(self, tmp_path: Path) -> None:
        root = tmp_path / "bk"
        for skill in ("one", "two"):
            src = tmp_path / "skills" / skill / "SKILL.md"
            src.parent.mkdir(parents=True)
            src.write_text(skill)
            _backup_file(src, root)
        assert sorted(p.read_text() for p in root.rglob("SKILL.md")) == ["one", "two"]


class TestWhatIsBackedUp:
    @pytest.fixture
    def pair(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        src, dst = tmp_path / "src.md", tmp_path / "out" / "dst.md"
        src.write_text("new\n")
        dst.parent.mkdir()
        return src, dst, tmp_path / "bk"

    def test_carters_own_previous_output_is_not_copied(self, pair) -> None:
        src, dst, root = pair
        dst.write_text("old carter output\n")
        recorded = _sha256(dst)
        manifest: dict = {"files": [], "file_hashes": {str(dst): recorded}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert not root.exists()
        assert manifest["file_hashes"][str(dst)] == _sha256(src)

    def test_an_edit_is_copied(self, pair) -> None:
        src, dst, root = pair
        dst.write_text("old carter output\n")
        recorded = _sha256(dst)
        dst.write_text("my edit\n")
        manifest: dict = {"files": [], "file_hashes": {str(dst): recorded}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert [p.read_text() for p in root.rglob("dst.md")] == ["my edit\n"]

    def test_a_file_carter_never_wrote_is_copied(self, pair) -> None:
        src, dst, root = pair
        dst.write_text("a stranger\n")
        manifest: dict = {"files": [], "file_hashes": {}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert [p.read_text() for p in root.rglob("dst.md")] == ["a stranger\n"]


class TestInstallBackups:
    def test_an_upgrade_of_carters_own_output_leaves_no_backup(
        self, base_dir: Path, fake_opencode, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        real = components._render_opencode_agents
        monkeypatch.setattr(
            components,
            "_render_opencode_agents",
            lambda b=None: {n: c + "\nnew release\n" for n, c in real(b).items()},
        )
        orchestrator.run(base_dir=base_dir, verbosity=1)
        assert not paths.backups_dir(base_dir).exists()

    def test_manifest_drops_hashes_of_paths_it_no_longer_lists(
        self, base_dir: Path, fake_opencode
    ) -> None:
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        manifest = components.read_manifest(base_dir)
        assert manifest is not None
        manifest["file_hashes"]["/gone/file.md"] = "0" * 64
        components.write_manifest(manifest, base_dir)
        written = components.read_manifest(base_dir)
        assert written is not None
        assert "/gone/file.md" not in written["file_hashes"]
        assert set(written["file_hashes"]) <= set(written["files"])

    def test_rerender_writes_under_a_stamp_dir_and_keeps_an_edit(
        self, base_dir: Path, fake_opencode
    ) -> None:
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        agent = paths._opencode_base(base_dir) / "agents" / "carter-engineer.md"
        agent.write_text("my edit\n")
        components.rerender_agents(base_dir)
        root = paths.backups_dir(base_dir)
        assert not (root / "agents").exists()
        (stamp_dir,) = root.iterdir()
        assert datetime.strptime(stamp_dir.name, backups.STAMP_FORMAT)
        assert [p.read_text() for p in stamp_dir.rglob("carter-engineer.md")] == ["my edit\n"]

    def test_retired_skill_is_removed_without_a_copy(self, base_dir: Path) -> None:
        skill = paths._opencode_base(base_dir) / "skills" / "carter-triage"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("old\n")
        previous = {"file_hashes": {str(skill / "SKILL.md"): _sha256(skill / "SKILL.md")}}
        assert components.remove_retired_skills(base_dir, previous) == 1
        assert not skill.exists()
        assert not paths.backups_dir(base_dir).exists()

    def test_install_prunes_and_reports_with_v(self, base_dir: Path, fake_opencode, capsys) -> None:
        fake_opencode()
        old = paths.backups_dir(base_dir) / _stamp(30)
        old.mkdir(parents=True)
        orchestrator.run(base_dir=base_dir, verbosity=2)
        assert not old.exists()
        assert "pruned 1 old backups" in capsys.readouterr().out


class TestPrune:
    def _make(self, root: Path, *names: str) -> None:
        for name in names:
            (root / name).mkdir(parents=True)
            (root / name / "kept.txt").write_text(name)

    def test_removes_only_stamp_dirs_older_than_the_retention(self, tmp_path: Path) -> None:
        assert backups.RETENTION_DAYS == 15
        old, edge, fresh = _stamp(16), _stamp(14.9), _stamp(1)
        self._make(tmp_path, old, edge, fresh)
        assert backups.prune(tmp_path, NOW) == 1
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted([edge, fresh])

    def test_the_name_is_the_clock_not_the_mtime(self, tmp_path: Path) -> None:
        fresh = _stamp(1)
        self._make(tmp_path, fresh)
        os.utime(tmp_path / fresh, (0, 0))  # as a copy2 of an ancient file would leave it
        assert backups.prune(tmp_path, NOW) == 0

    def test_legacy_and_foreign_names_are_untouched(self, tmp_path: Path) -> None:
        self._make(tmp_path, "agents", "mine", "2020-01-01", "2020010T000000", "x" + _stamp(99))
        (tmp_path / "stray.txt").write_text("x")
        assert backups.prune(tmp_path, NOW) == 0
        assert len(list(tmp_path.iterdir())) == 6

    def test_a_missing_root_is_fine(self, tmp_path: Path) -> None:
        assert backups.prune(tmp_path / "nope", NOW) == 0

    def test_a_symlink_named_like_a_stamp_is_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "precious").write_text("x")
        root = tmp_path / "bk"
        root.mkdir()
        (root / _stamp(99)).symlink_to(outside, target_is_directory=True)
        assert backups.prune(root, NOW) == 0
        assert (outside / "precious").read_text() == "x"

    def test_a_symlink_inside_an_old_dir_is_removed_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "precious").write_text("x")
        root = tmp_path / "bk"
        self._make(root, _stamp(99))
        (root / _stamp(99) / "link").symlink_to(outside, target_is_directory=True)
        assert backups.prune(root, NOW) == 1
        assert (outside / "precious").read_text() == "x"
