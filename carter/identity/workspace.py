"""Which workspace a directory belongs to, as the key used in ``[workspaces."<path>"]``.

The key is the resolved absolute path (symlinks followed) of the nearest ancestor that
holds ``.carter/carter.yaml``; with none, the resolved starting directory. ``carter
update`` pins policy under the same key, so both must use this.
"""

from __future__ import annotations

from pathlib import Path


def workspace_key(start: Path | None = None) -> str:
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".carter" / "carter.yaml").is_file():
            return str(candidate)
    return str(here)
