"""``atomic_write_bytes``: the one way Carter replaces a file the user also owns."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from carter.install.atomic import atomic_write_bytes


def test_creates_parents_and_a_0600_file(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "f"
    assert atomic_write_bytes(target, b"x") == target
    assert target.read_bytes() == b"x"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_an_existing_file_keeps_its_mode(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_text("old")
    target.chmod(0o644)
    atomic_write_bytes(target, b"new")
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_follow_symlinks_writes_the_target_and_keeps_the_link(tmp_path: Path) -> None:
    real = tmp_path / "dot" / "cfg"
    real.parent.mkdir()
    real.write_text("old")
    link = tmp_path / "cfg"
    link.symlink_to(real)
    written = atomic_write_bytes(link, b"new", follow_symlinks=True)
    assert link.is_symlink() and real.read_bytes() == b"new"
    assert written == Path(os.path.realpath(real))


def test_without_follow_symlinks_the_link_is_replaced(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.write_text("old")
    link = tmp_path / "cfg"
    link.symlink_to(real)
    atomic_write_bytes(link, b"new")
    assert not link.is_symlink() and real.read_text() == "old"


def test_failure_leaves_the_old_file_and_no_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f"
    target.write_text("old")
    monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["f"]


def test_no_fd_leaks_when_fdopen_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = len(os.listdir("/proc/self/fd")) if Path("/proc/self/fd").exists() else None
    monkeypatch.setattr(os, "fdopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no")))
    for _ in range(5):
        with pytest.raises(OSError):
            atomic_write_bytes(tmp_path / "f", b"x")
    if before is not None:
        assert len(os.listdir("/proc/self/fd")) <= before
    assert list(tmp_path.iterdir()) == []
