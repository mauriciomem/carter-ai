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
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import carter
from carter.broker import DEVOPS_AGENT
from carter.guard import consent, gitconfig
from carter.guard.state import GuardState
from carter.identity import isolation
from carter.install.paths import (
    headless_profile_path,
    isolation_path,
    plugin_dir,
    run_dir,
    token_path,
)

__all__ = [
    "PluginInstallError",
    "broker_tools",
    "cleanup_dirs",
    "headless_profile_path",
    "install",
    "render_headless",
    "isolation_path",
    "plan",
    "plugin_dir",
    "remove",
    "run_dir",
    "unexpected_files",
]

Echo = Callable[[str], None]
SOURCE = Path(__file__).resolve().parents[1] / "plugin"
PLUGIN_FILES = ("core.ts", "broker.ts")  # installed byte-identical next to the rendered index.ts
TOOL_DIRS = ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin")  # never PATH at runtime
PLACEHOLDERS = ("__CARTER_ISOLATION_SHA256__", "__CARTER_VERSION__")
TEMP_ROOTS = ("/tmp", "/var/tmp", "/private/tmp", "/private/var/folders", "/var/folders")
RESTART = "restart the OpenCode server so it loads the plugin"
BROKER_AGENT = DEVOPS_AGENT  # freeze B10: the only agent that can use B


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


def find_tool(name: str, dirs: tuple[str, ...] = TOOL_DIRS) -> str:
    """Absolute path of ``name`` in the fixed directories (empty when absent). B resolves ``git``
    and ``gh`` here, once, in the human-run install: the runtime never searches ``PATH``."""
    for directory in dirs:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


def broker_tools() -> tuple[str, str]:
    """``(git, gh)`` absolute paths for ``plugin.b_git`` / ``plugin.b_gh`` (``gh`` may be empty)."""
    return find_tool("git"), find_tool("gh")


def broker_enabled(state: GuardState) -> bool:
    """B is registered only with ``g2`` accepted at revision 3 and a git that was found."""
    return consent.broker_wanted(state) and bool(broker_tools()[0])


def render_headless() -> str:
    """The static headless profile (freeze B8): denies B for devops, the only agent that has it.

    Per-agent permissions, not ``policies`` (a global ``tool.use`` policy never matches a plugin
    tool, spike A6). It applies to the process that starts the server: ``opencode run
    --standalone`` or the run that starts the service; a running service ignores it."""
    deny = [
        {"action": name, "resource": "*", "effect": "deny"} for name in ("carter_push", "carter_pr")
    ]
    doc = {"agents": {BROKER_AGENT: {"permissions": deny}}}
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def isolation_document(
    base_dir: Path | None, state: GuardState, python: str, carter_bin: str
) -> bytes:
    """The canonical bytes of ``isolation.json`` (raises E-FALSE-MISSING before any write)."""
    git, gh = broker_tools()
    doc = isolation.render(
        home=str(Path.home()),
        python_path=python,
        carter_path=carter_bin,
        false_path=isolation.resolve_false(),
        pat_file=str(token_path(base_dir)),
        declined_groups=tuple(consent.declined_groups(state)),
        b_enabled=broker_enabled(state),
        b_git=git if broker_enabled(state) else "",
        b_gh=gh if broker_enabled(state) else "",
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
    files = [Planned(isolation_path(base_dir), iso_bytes.decode(), 0o600)]
    files += [
        Planned(folder / name, (SOURCE / name).read_text("utf-8"), 0o644) for name in PLUGIN_FILES
    ]
    files.append(Planned(folder / "index.ts", index, 0o644))
    if broker_enabled(state):
        files.append(Planned(headless_profile_path(base_dir), render_headless(), 0o644))
    return files


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
    if broker_enabled(state):
        echo("B tools: carter_push and carter_pr are enabled for devops (every use asks you).")
    elif consent.broker_wanted(state):
        echo(
            "⚠ B tools not enabled: no git found in /usr/bin, /bin, /usr/local/bin or "
            "/opt/homebrew/bin"
        )
    return out


def remove(base_dir: Path | None, state: GuardState, echo: Echo) -> None:
    """Remove the plugin, ``isolation.json`` and the ``run/`` files, only where unchanged."""
    folder = plugin_dir(base_dir)
    ours = (
        folder / "index.ts", *(folder / n for n in PLUGIN_FILES), isolation_path(base_dir),
        headless_profile_path(base_dir),
    )  # fmt: skip
    for path in ours:
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
    ours = {plugin_dir(base_dir) / name for name in ("index.ts", *PLUGIN_FILES)}
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
