"""File hashing, backup and file installation primitives."""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from carter.home import tilde
from carter.install.backups import BackupRoot
from carter.install.console import log_debug, log_ok, log_skip, log_warn
from carter.install.ownership import sha256_bytes


def _sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _mirror(path: Path) -> Path:
    """Where a backup of ``path`` goes under ``backups/<stamp>/``: its own location, so two
    ``SKILL.md`` never share a name. Relative to ``$HOME``; outside it, without the anchor.
    The path is normalised first, so a ``..`` cannot climb out of the backup root."""
    p = Path(os.path.abspath(path))
    try:
        return p.relative_to(Path.home())
    except ValueError:
        return p.relative_to(p.anchor)


def _backup_file(path: Path, backup_root: BackupRoot) -> Path | None:
    """Copy ``path`` to ``backup_root/<its own path>`` (0600) and return the copy.

    Nothing is copied (``None``) for a missing file or one that is not a regular file: a
    symlink is replaced by the installers, never written through, so its target stays as it is.
    The copy is created exclusively and without following links, in a folder this run made."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        log_warn(f"{tilde(path)} is not a regular file; not copied")
        return None
    root = backup_root.make()
    dest = root / _mirror(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.parent.resolve().is_relative_to(root.resolve()):
        raise OSError(f"{dest.parent} is outside {root}; refusing to copy")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    with (
        os.fdopen(os.open(path, os.O_RDONLY | nofollow), "rb") as src,
        os.fdopen(
            os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600), "wb"
        ) as out,
    ):
        shutil.copyfileobj(src, out)
    os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns))  # a copy keeps its age
    backup_root.copied += 1
    log_debug(f"Backed up {path} → {dest}")
    return dest


def _replace_with(dst: Path, write: Callable[[Path], object]) -> None:
    """Have ``write`` fill a new file next to ``dst`` and rename it over ``dst``. The rename
    replaces a link, never what it points to. The mode is the old file's, else 0644."""
    mode = 0o644
    with contextlib.suppress(OSError):
        old = os.lstat(dst)
        if stat.S_ISREG(old.st_mode):
            mode = stat.S_IMODE(old.st_mode)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.")
    os.close(fd)
    try:
        os.chmod(tmp, mode)
        write(Path(tmp))
        os.replace(tmp, dst)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _control_target(path: Path) -> Path | None:
    """Where ``path`` really lives if that is inside ``~/.carter`` or on a control path (the
    shell gate's list), else ``None``. A link to a file dotfiles manage is fine; one into
    Carter's own state is not, and Carter must not rewrite what it points to."""
    from carter.identity.rules import load_rules

    home = Path(os.path.realpath(Path.home()))
    roots = [home / ".carter", *(home / entry[2:] for entry in load_rules().control_paths)]
    real = Path(os.path.realpath(path))
    return real if any(real.is_relative_to(root) for root in roots) else None


def _install_content(
    dst: Path,
    content_hash: str,
    write: Callable[[Path], object],
    manifest: dict,
    backup_root: BackupRoot,
) -> str:
    """Install ``dst`` via ``write(path)`` unless it already has ``content_hash``.

    A differing existing file is backed up first, unless it is the output Carter recorded
    last time (``manifest["file_hashes"]`` is seeded with the previous install's hashes):
    that is reproducible, so only an edit or a file Carter never wrote is copied. The file is
    always written next to ``dst`` and renamed over it, so a symlink at ``dst`` (or swapped in
    meanwhile) is replaced and never written through: whatever it pointed to is untouched.
    ``dst`` is always recorded in the manifest with ``content_hash``. Returns ``created``,
    ``updated`` or ``unchanged``.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink():
        log_warn(f"{tilde(dst)} is a symlink; replacing the link, not what it points to")
        status = "updated"
    elif dst.exists():
        current = _sha256(dst)
        if current == content_hash:
            log_skip(tilde(dst))
            status = "unchanged"
        else:
            if current != manifest["file_hashes"].get(str(dst)):
                _backup_file(dst, backup_root)
            status = "updated"
    else:
        status = "created"
    if status != "unchanged":
        _replace_with(dst, write)
        log_ok(tilde(dst), "updated" if status == "updated" else "")
    manifest["files"].append(str(dst))
    manifest["file_hashes"][str(dst)] = content_hash
    return status


def _install_rendered_file(
    content: str,
    dst: Path,
    manifest: dict,
    backup_root: BackupRoot,
) -> str:
    """Write already-rendered ``content`` to ``dst`` (no source file to copy).

    Used to install rendered output, e.g. agents rendered from ``templates/``
    with OpenCode V2 ``permissions:`` frontmatter. Same backup/manifest/hash
    semantics as ``_install_file``.
    """
    return _install_content(
        dst,
        sha256_bytes(content.encode()),
        lambda target: target.write_text(content, encoding="utf-8"),
        manifest,
        backup_root,
    )


def _install_file(
    src: Path,
    dst: Path,
    manifest: dict,
    backup_root: BackupRoot,
) -> str:
    """Copy src to dst. Returns status: 'created', 'updated', or 'unchanged'."""
    return _install_content(
        dst, _sha256(src), lambda target: shutil.copy2(src, target), manifest, backup_root
    )
