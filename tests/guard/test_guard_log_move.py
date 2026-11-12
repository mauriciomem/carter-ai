"""``guard.log`` lives in ``state/audit/``; one written by an older hook in ``run/`` moves there."""

from __future__ import annotations

import stat
from pathlib import Path

from carter.guard import hooks
from carter.guard.state import GuardState
from carter.install import orchestrator, paths
from carter.install.uninstall import uninstall

LINE = "2026-01-01T00:00:00Z E-GUARD-UNSIGNED abc1234\n"


def old_log(base_dir: Path) -> Path:
    return paths.run_dir(base_dir) / "guard.log"


def new_log(base_dir: Path) -> Path:
    return paths.guard_log_path(base_dir)


def write_old(base_dir: Path, text: str = LINE) -> None:
    old_log(base_dir).parent.mkdir(parents=True)
    old_log(base_dir).write_text(text)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_new_location_is_under_the_audit_store(tmp_path: Path) -> None:
    assert new_log(tmp_path) == tmp_path / "carter" / "state" / "audit" / "guard.log"


class TestMigrate:
    def test_an_old_log_moves_private(self, tmp_path: Path) -> None:
        write_old(tmp_path)
        hooks.migrate_guard_log(tmp_path)
        assert new_log(tmp_path).read_text() == LINE
        assert not old_log(tmp_path).exists()
        assert (mode(new_log(tmp_path)), mode(new_log(tmp_path).parent)) == (0o600, 0o700)

    def test_it_appends_to_a_log_that_is_already_there(self, tmp_path: Path) -> None:
        write_old(tmp_path, "older\n")
        new_log(tmp_path).parent.mkdir(parents=True)
        new_log(tmp_path).write_text("newer\n")
        hooks.migrate_guard_log(tmp_path)
        assert new_log(tmp_path).read_text() == "newer\nolder\n"
        assert not old_log(tmp_path).exists()

    def test_nothing_to_move_creates_nothing(self, tmp_path: Path) -> None:
        hooks.migrate_guard_log(tmp_path)
        assert not (tmp_path / "carter").exists()

    def test_a_symlink_is_left_alone(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret"
        secret.write_text("not a log")
        old_log(tmp_path).parent.mkdir(parents=True)
        old_log(tmp_path).symlink_to(secret)
        hooks.migrate_guard_log(tmp_path)
        assert not new_log(tmp_path).exists() and old_log(tmp_path).is_symlink()

    def test_an_unwritable_destination_keeps_the_old_log_and_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        write_old(tmp_path)
        (tmp_path / "carter" / "state").write_text("a file where the directory should be")
        hooks.migrate_guard_log(tmp_path)
        assert old_log(tmp_path).read_text() == LINE


class TestWhenItRuns:
    def test_a_guard_install_writes_the_new_hook_and_moves_the_log(self, tmp_path: Path) -> None:
        write_old(tmp_path)
        assert hooks.install_script(tmp_path, GuardState()) == "created"
        assert new_log(tmp_path).read_text() == LINE
        assert not old_log(tmp_path).exists()

    def test_an_edited_script_keeps_writing_where_it_wrote_so_nothing_moves(
        self, tmp_path: Path
    ) -> None:
        state = GuardState()
        hooks.install_script(tmp_path, state)
        script = hooks.script_path(tmp_path)
        script.write_text(script.read_text() + "# mine\n")
        write_old(tmp_path)
        assert hooks.install_script(tmp_path, state) == "edited-kept"
        assert old_log(tmp_path).read_text() == LINE

    def test_uninstall_moves_it_even_without_guards(self, base_dir: Path, fake_opencode) -> None:
        fake_opencode()
        orchestrator.run(base_dir=base_dir, verbosity=1)
        write_old(base_dir)
        uninstall(base_dir)
        assert new_log(base_dir).read_text() == LINE
        assert not old_log(base_dir).exists()
