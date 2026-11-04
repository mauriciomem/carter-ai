"""Render, install and remove the Carter OpenCode plugin and its companions (plan 004 step 26).

RFC-0007 §4.3, App C.6.2, freeze G2/G3/G4. What lands on the host, all recorded in guard state
(``files``, sha256) and written atomically:

- ``~/.config/opencode/plugins/carter/index.ts`` (rendered: the sha256 of the final
  ``isolation.json`` bytes and the Carter version replace two placeholders) and ``core.ts``
  (byte-identical to the source). OpenCode discovers the directory; nothing is registered.
- ``~/.carter/isolation.json`` (the block, canonical bytes), ``~/.carter/run/`` and
  ``~/.carter/run/gh-empty/`` (0700, empty; the plugin writes ``run/plugin-status/<pid>.json``).

A file the user edited is kept and reported, never overwritten. A plugin whose baked hash does not
match ``isolation.json`` refuses to create agent shells (``E-ISOLATION-MISSING``), so a kept edit
fails closed. The install never runs when no root-owned ``false`` exists (C.2.1): nothing is
written then. Python and ``carter`` paths are those of the running Carter and must exist; a path
in a temporary directory is refused (an install must not point the gate at a vanishing file).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import carter
from carter.guard import consent, gitconfig
from carter.guard.state import GuardState
from carter.identity import isolation
from carter.install.paths import isolation_path, plugin_dir, run_dir, token_path

__all__ = [
    "PluginInstallError",
    "cleanup_dirs",
    "install",
    "isolation_path",
    "plan",
    "plugin_dir",
    "remove",
    "run_dir",
    "unexpected_files",
]

Echo = Callable[[str], None]
SOURCE = Path(__file__).resolve().parents[1] / "plugin"
PLACEHOLDERS = ("__CARTER_ISOLATION_SHA256__", "__CARTER_VERSION__")
TEMP_ROOTS = ("/tmp", "/var/tmp", "/private/tmp", "/private/var/folders", "/var/folders")
RESTART = "restart the OpenCode server so it loads the plugin"


class PluginInstallError(Exception):
    """A precondition failed; nothing was written."""


def is_temporary(path: str) -> bool:
    real = os.path.realpath(path)
    roots = {os.path.realpath(r) for r in (*TEMP_ROOTS, tempfile.gettempdir())}
    return any(real == r or real.startswith(r + os.sep) for r in roots)


def find_paths(*, allow_temp: bool = False) -> tuple[str, str]:
    """``(python_path, carter_path)`` of the running Carter, validated."""
    python = sys.executable
    sibling = Path(python).parent / "carter"
    carter_bin = str(sibling) if sibling.exists() else (shutil.which("carter") or "")
    for label, path in (("python", python), ("carter", carter_bin)):
        if not path or not os.path.isabs(path) or not os.access(path, os.X_OK):
            raise PluginInstallError(f"cannot find an executable {label} for the plugin ({path!r})")
        if not allow_temp and is_temporary(path):
            raise PluginInstallError(
                f"the {label} path {path} is in a temporary directory; install Carter "
                "(`uv tool install carter-ai`) and run `carter guard install` from it"
            )
    return python, carter_bin


def render_index(iso_sha256: str, version: str) -> str:
    text = (SOURCE / "index.ts").read_text("utf-8")
    for placeholder, value in zip(PLACEHOLDERS, (iso_sha256, version), strict=True):
        if placeholder not in text:
            raise PluginInstallError(f"index.ts has no {placeholder}")
        text = text.replace(placeholder, value)
    return text


def isolation_document(
    base_dir: Path | None, state: GuardState, python: str, carter_bin: str
) -> bytes:
    """The canonical bytes of ``isolation.json`` (raises E-FALSE-MISSING before any write)."""
    doc = isolation.render(
        home=str(Path.home()),
        python_path=python,
        carter_path=carter_bin,
        false_path=isolation.resolve_false(),
        pat_file=str(token_path(base_dir)),
        declined_groups=tuple(consent.declined_groups(state)),
    )
    return isolation.canonical_bytes(doc)


@dataclass
class Planned:
    path: Path
    content: str
    mode: int


@dataclass
class InstallResult:
    statuses: dict[str, str] = field(default_factory=dict)  # path -> created|updated|...
    kept: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(s in ("created", "updated") for s in self.statuses.values())


def plan(base_dir: Path | None, state: GuardState, *, allow_temp: bool = False) -> list[Planned]:
    """Every file the install writes, in write order (the isolation block before the plugin)."""
    python, carter_bin = find_paths(allow_temp=allow_temp)
    iso_bytes = isolation_document(base_dir, state, python, carter_bin)
    index = render_index(isolation.sha256_hex(iso_bytes), carter.__version__)
    folder = plugin_dir(base_dir)
    return [
        Planned(isolation_path(base_dir), iso_bytes.decode(), 0o600),
        Planned(folder / "core.ts", (SOURCE / "core.ts").read_text("utf-8"), 0o644),
        Planned(folder / "index.ts", index, 0o644),
    ]


def install(
    base_dir: Path | None, state: GuardState, echo: Echo, *, allow_temp: bool = False
) -> InstallResult:
    """Write the files (atomically, hash-recorded); keep and report any the user changed."""
    files = plan(base_dir, state, allow_temp=allow_temp)  # may raise: nothing written yet
    out = InstallResult()
    run = run_dir(base_dir)
    for directory in (run, run / "gh-empty"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    for item in files:
        status = gitconfig.install_file(item.path, item.content, state, mode=item.mode)
        out.statuses[str(item.path)] = status
        if status == "edited-kept":
            out.kept.append(str(item.path))
            echo(f"⚠ kept your edited {item.path}; delete it and run `carter guard install`")
    if out.kept:
        echo(
            "⚠ the plugin and isolation.json no longer match: agent shells are refused until fixed"
        )
    if out.changed:
        echo(f"plugin installed: {plugin_dir(base_dir)} ({RESTART})")
    else:
        echo(f"plugin up to date: {plugin_dir(base_dir)}")
    return out


def remove(base_dir: Path | None, state: GuardState, echo: Echo) -> None:
    """Remove the plugin, ``isolation.json`` and the ``run/`` files, only where unchanged."""
    folder = plugin_dir(base_dir)
    for path in (folder / "index.ts", folder / "core.ts", isolation_path(base_dir)):
        if state.owned_unchanged(path):
            path.unlink()
            echo(f"  removed {path}")
        elif path.exists():
            echo(f"  kept {path}: changed since Carter wrote it; remove it yourself: rm {path}")
        state.forget_file(path)
    run = run_dir(base_dir)
    status = run / "plugin-status"
    if status.is_dir():
        for entry in status.glob("*.json"):
            entry.unlink()
        _rmdir(status)
    cleanup_dirs(base_dir)


def _rmdir(path: Path) -> None:
    with contextlib.suppress(OSError):  # not empty, or already gone: leave it
        path.rmdir()


def cleanup_dirs(base_dir: Path | None) -> None:
    """Remove the (empty) directories a failed install created."""
    folder = plugin_dir(base_dir)
    for directory in (run_dir(base_dir) / "gh-empty", run_dir(base_dir), folder, folder.parent):
        _rmdir(directory)


def unexpected_files(base_dir: Path | None) -> list[str]:
    """Plugin code Carter did not write, by name (D66): ``plugin/`` and ``plugins/`` minus ours."""
    ours = {plugin_dir(base_dir) / "index.ts", plugin_dir(base_dir) / "core.ts"}
    root = plugin_dir(base_dir).parent.parent
    found: list[str] = []
    for sub in ("plugin", "plugins"):
        folder = root / sub
        if folder.is_dir():
            found += [
                str(p.relative_to(root))
                for p in sorted(folder.rglob("*"))
                if p.is_file() and p not in ours
            ]
    return found
