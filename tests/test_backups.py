"""Backups under ``backups/<UTC stamp>/``: mirrored paths, own output not copied, pruning."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from carter.install import backups, components, files, orchestrator, paths
from carter.install.backups import BackupRoot
from carter.install.files import (
    _backup_file,
    _install_file,
    _install_rendered_file,
    _mirror,
    _sha256,
)
from carter.install.prereqs import PrerequisiteError

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
        root = BackupRoot(tmp_path / "bk")
        assert not _mirror(source).is_absolute()
        assert ".." not in _mirror(source).parts
        assert (root.path / _mirror(source)).resolve().is_relative_to(root.path.resolve())

    def test_two_files_with_one_name_get_two_destinations(self, tmp_path: Path) -> None:
        root = BackupRoot(tmp_path / "bk")
        for skill in ("one", "two"):
            src = tmp_path / "skills" / skill / "SKILL.md"
            src.parent.mkdir(parents=True)
            src.write_text(skill)
            _backup_file(src, root)
        assert sorted(p.read_text() for p in root.path.rglob("SKILL.md")) == ["one", "two"]


class TestWhatIsBackedUp:
    @pytest.fixture
    def pair(self, tmp_path: Path) -> tuple[Path, Path, BackupRoot]:
        src, dst = tmp_path / "src.md", tmp_path / "out" / "dst.md"
        src.write_text("new\n")
        dst.parent.mkdir()
        return src, dst, BackupRoot(tmp_path / "bk")

    def test_carters_own_previous_output_is_not_copied(self, pair) -> None:
        src, dst, root = pair
        dst.write_text("old carter output\n")
        recorded = _sha256(dst)
        manifest: dict = {"files": [], "file_hashes": {str(dst): recorded}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert not root.parent.exists()
        assert manifest["file_hashes"][str(dst)] == _sha256(src)

    def test_an_edit_is_copied(self, pair) -> None:
        src, dst, root = pair
        dst.write_text("old carter output\n")
        recorded = _sha256(dst)
        dst.write_text("my edit\n")
        manifest: dict = {"files": [], "file_hashes": {str(dst): recorded}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert [p.read_text() for p in root.path.rglob("dst.md")] == ["my edit\n"]

    def test_a_file_carter_never_wrote_is_copied(self, pair) -> None:
        src, dst, root = pair
        dst.write_text("a stranger\n")
        manifest: dict = {"files": [], "file_hashes": {}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert [p.read_text() for p in root.path.rglob("dst.md")] == ["a stranger\n"]

    def test_a_link_swapped_in_after_the_check_is_replaced_not_written_through(
        self, pair, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src, dst, root = pair
        dst.write_text("old\n")
        victim = tmp_path / "victim"
        victim.write_text("keep\n")
        real = files._sha256

        def racing(path: Path) -> str:
            digest = real(path)
            if path == dst:  # the window between the check and the write
                dst.unlink()
                dst.symlink_to(victim)
            return digest

        monkeypatch.setattr(files, "_sha256", racing)
        manifest: dict = {"files": [], "file_hashes": {}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert victim.read_text() == "keep\n"
        assert not dst.is_symlink() and dst.read_text() == "new\n"

    def test_the_file_keeps_its_mode_and_a_new_one_is_0644(self, pair) -> None:
        src, dst, root = pair
        dst.write_text("old\n")
        dst.chmod(0o600)
        manifest: dict = {"files": [], "file_hashes": {str(dst): _sha256(dst)}}
        _install_rendered_file("new\n", dst, manifest, root)  # rendered: the old mode stays
        assert stat.S_IMODE(dst.stat().st_mode) == 0o600
        src.chmod(0o755)
        other = dst.with_name("other.md")
        _install_file(src, other, manifest, root)  # copied: the source's mode, as copy2 gives
        assert stat.S_IMODE(other.stat().st_mode) == 0o755
        fresh = dst.with_name("fresh.md")
        _install_rendered_file("x\n", fresh, manifest, root)
        assert stat.S_IMODE(fresh.stat().st_mode) == 0o644

    @pytest.mark.parametrize("target", ["exists", "dangling"])
    def test_a_symlinked_destination_is_replaced_never_written_through(
        self, pair, tmp_path: Path, target: str
    ) -> None:
        src, dst, root = pair
        victim = tmp_path / "victim"
        if target == "exists":
            victim.write_text("keep\n")
        dst.symlink_to(victim)
        manifest: dict = {"files": [], "file_hashes": {}}
        assert _install_file(src, dst, manifest, root) == "updated"
        assert not dst.is_symlink() and dst.read_text() == "new\n"
        assert victim.read_text() == "keep\n" if target == "exists" else not victim.exists()
        assert not root.parent.exists()  # nothing of the target was touched, so nothing to copy
        assert [p.name for p in dst.parent.iterdir()] == ["dst.md"]  # no temp file left behind


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


class TestBackupRoot:
    """A backup copy can never land through a link somebody planted (security review B, #1)."""

    @staticmethod
    def _source(tmp_path: Path, text: str = "my edit\n") -> Path:
        src = tmp_path / "home" / "agents" / "carter-x.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(text)
        return src

    def test_the_folder_appears_on_first_use_private_and_so_do_the_copies(
        self, tmp_path: Path
    ) -> None:
        root = BackupRoot(tmp_path / "bk", NOW)
        assert not root.parent.exists()
        copy = _backup_file(self._source(tmp_path), root)
        assert copy is not None and copy.read_text() == "my edit\n"
        assert root.path.name == NOW.strftime(backups.STAMP_FORMAT)
        assert stat.S_IMODE(root.path.stat().st_mode) == 0o700
        assert stat.S_IMODE(copy.stat().st_mode) == 0o600

    def test_a_name_that_is_taken_moves_to_the_next_second(self, tmp_path: Path) -> None:
        (tmp_path / "bk" / _stamp(0)).mkdir(parents=True)
        root = BackupRoot(tmp_path / "bk", NOW)
        _backup_file(self._source(tmp_path), root)
        assert root.path.name == (NOW + timedelta(seconds=1)).strftime(backups.STAMP_FORMAT)
        assert not list((tmp_path / "bk" / _stamp(0)).iterdir())  # the taken folder is untouched

    def test_a_link_planted_at_the_destination_is_not_written_through(self, tmp_path: Path) -> None:
        src = self._source(tmp_path)
        victim = tmp_path / "guard"
        victim.write_text("the real guard\n")
        planted = tmp_path / "bk" / _stamp(0) / _mirror(src)
        planted.parent.mkdir(parents=True)
        planted.symlink_to(victim)
        root = BackupRoot(tmp_path / "bk", NOW)
        copy = _backup_file(src, root)
        assert victim.read_text() == "the real guard\n"
        assert copy is not None and not copy.is_symlink() and copy.read_text() == "my edit\n"

    def test_a_link_planted_as_a_parent_folder_is_not_followed(self, tmp_path: Path) -> None:
        src = self._source(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        planted = tmp_path / "bk" / _stamp(0) / _mirror(src).parent
        planted.parent.mkdir(parents=True)
        planted.symlink_to(elsewhere, target_is_directory=True)
        copy = _backup_file(src, BackupRoot(tmp_path / "bk", NOW))
        assert list(elsewhere.iterdir()) == []
        assert copy is not None and copy.read_text() == "my edit\n"

    def test_a_symlinked_backups_folder_is_refused(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (tmp_path / "bk").symlink_to(elsewhere, target_is_directory=True)
        with pytest.raises(OSError, match="symlink"):
            _backup_file(self._source(tmp_path), BackupRoot(tmp_path / "bk", NOW))
        assert list(elsewhere.iterdir()) == []

    def test_a_symlinked_source_is_skipped_and_its_target_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        link = tmp_path / "link.md"
        link.symlink_to(self._source(tmp_path))
        root = BackupRoot(tmp_path / "bk", NOW)
        assert _backup_file(link, root) is None
        assert not root.parent.exists()

    def test_install_does_not_write_through_links_planted_in_the_next_stamp_folders(
        self, base_dir: Path, fake_opencode
    ) -> None:
        """The reviewed attack: link ``backups/<next seconds>/<agent path>`` at the guard script,
        edit the agent, wait for ``carter install``. The script must stay as it was."""
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        agent = paths._opencode_base(base_dir) / "agents" / "carter-engineer.md"
        guard = paths.guard_script_path(base_dir)
        guard.parent.mkdir(parents=True)
        guard.write_text("the real guard\n")
        agent.write_text("my edit\n")
        now = datetime.now(UTC)
        for seconds in range(-1, 6):
            link = (
                paths.backups_dir(base_dir)
                / (now + timedelta(seconds=seconds)).strftime(backups.STAMP_FORMAT)
                / _mirror(agent)
            )
            link.parent.mkdir(parents=True)
            link.symlink_to(guard)
        orchestrator.run(base_dir=base_dir, verbosity=1)
        assert guard.read_text() == "the real guard\n"
        copies = [p for p in paths.backups_dir(base_dir).rglob(agent.name) if not p.is_symlink()]
        assert [c.read_text() for c in copies] == ["my edit\n"]


class TestInstallStopsEarly:
    def test_a_backups_folder_that_cannot_be_used_stops_the_install_before_any_write(
        self, base_dir: Path, fake_opencode, tmp_path: Path
    ) -> None:
        fake_opencode()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        paths.backups_dir(base_dir).parent.mkdir(parents=True)
        paths.backups_dir(base_dir).symlink_to(elsewhere, target_is_directory=True)
        with pytest.raises(PrerequisiteError, match="symlink"):
            orchestrator.run(base_dir=base_dir, verbosity=1)
        assert not paths.manifest_path(base_dir).exists()
        assert not (paths._opencode_base(base_dir) / "agents").exists()
        assert list(elsewhere.iterdir()) == []

    def test_a_run_that_copied_nothing_leaves_no_empty_stamp_folder(
        self, base_dir: Path, fake_opencode
    ) -> None:
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        assert not paths.backups_dir(base_dir).exists()

    def test_the_stamp_folder_stays_when_something_was_copied(
        self, base_dir: Path, fake_opencode
    ) -> None:
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        (paths._opencode_base(base_dir) / "agents" / "carter-pm.md").write_text("mine\n")
        orchestrator.run(base_dir=base_dir, verbosity=1)
        (stamp,) = paths.backups_dir(base_dir).iterdir()
        assert len(list(stamp.rglob("carter-pm.md"))) == 1


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

    def test_an_unreadable_folder_prunes_nothing_and_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def denied(self: Path):
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "iterdir", denied)
        assert backups.prune(tmp_path, NOW) == 0

    def test_the_stamp_format_is_written_once_so_every_folder_can_be_pruned(self) -> None:
        import carter

        literal = "%Y%m%dT%H%M%S"
        files = [p for p in Path(carter.__file__).parent.rglob("*.py") if literal in p.read_text()]
        assert [p.name for p in files] == ["home.py"]

    def test_a_symlinked_backups_folder_is_not_pruned_through(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "elsewhere"
        self._make(elsewhere, _stamp(99))
        (tmp_path / "bk").symlink_to(elsewhere, target_is_directory=True)
        assert backups.prune(tmp_path / "bk", NOW) == 0
        assert (elsewhere / _stamp(99) / "kept.txt").exists()

    def test_a_symlink_inside_an_old_dir_is_removed_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "precious").write_text("x")
        root = tmp_path / "bk"
        self._make(root, _stamp(99))
        (root / _stamp(99) / "link").symlink_to(outside, target_is_directory=True)
        assert backups.prune(root, NOW) == 1
        assert (outside / "precious").read_text() == "x"
