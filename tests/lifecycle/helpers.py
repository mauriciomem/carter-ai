"""Tree snapshots for the install/uninstall lifecycle tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# relative path -> (kind, permission bits, sha256 for files / link target for links)
Snapshot = dict[str, tuple[str, int, str]]


def tree_snapshot(root: Path) -> Snapshot:
    """Every entry under ``root`` (not ``root`` itself) by relative path, in stable order.

    Symlinks are recorded, never followed, so a link to the outside cannot pull foreign
    files into the comparison."""
    snap: Snapshot = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            path = Path(dirpath, name)
            rel = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode & 0o7777
            if path.is_symlink():
                snap[rel] = ("link", mode, os.readlink(path))
            elif path.is_dir():
                snap[rel] = ("dir", mode, "")
            else:
                snap[rel] = ("file", mode, hashlib.sha256(path.read_bytes()).hexdigest())
    return dict(sorted(snap.items()))


def tree_diff(before: Snapshot, after: Snapshot) -> str:
    """``+ added``, ``- removed`` and ``~ changed`` lines; empty when the trees are equal."""
    lines = [f"+ {p}" for p in after.keys() - before.keys()]
    lines += [f"- {p}" for p in before.keys() - after.keys()]
    lines += [f"~ {p}" for p in before.keys() & after.keys() if before[p] != after[p]]
    return "\n".join(sorted(lines, key=lambda line: line[2:]))
