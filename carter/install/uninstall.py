"""Carter uninstall — manifest-driven removal; without a manifest, the files this version ships.

``uninstall`` returns an :class:`UninstallReport`: the statuses and counts the CLI turns into
the closing report. Nothing here decides how it looks.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from carter import ui
from carter.home import tilde
from carter.identity import ConfigError, load_identity
from carter.identity.schema import IdentityConfig
from carter.install.backups import STAMP_FORMAT
from carter.install.components import _render_opencode_agents, read_manifest
from carter.install.console import log_ok, log_step, log_warn, set_verbosity
from carter.install.files import _backup_file, _mirror
from carter.install.mcp import global_config_files, remove_carter_servers
from carter.install.ownership import _hash_matches, _within
from carter.install.paths import (
    REPO_ROOT,
    _carter_base,
    _opencode_base,
    backups_dir,
    carter_config_path,
    knowledge_dir,
    manifest_path,
    run_dir,
)
from carter.install.paths import (
    managed_roots as _managed_roots,
)

# What happened to one file: deleted, deleted although the user edited it (a copy exists),
# left because it may hold the user's edits, or not Carter's business (absent / outside).
Status = Literal["removed", "edited-removed", "kept", "skipped"]

# Kept on purpose: (path under ~/.carter, why). A row appears only if the path holds files.
_KEPT = (
    ("memories", "your notes"),
    ("knowledge", "files you edited or added"),
    ("state/audit", "push approvals, ops log, guard log"),
    ("secrets", "revoke the token on GitHub too"),
    ("backups", "copies of files Carter replaced"),
)
_KEPT_CONFIG = "settings you changed"


@dataclass(frozen=True)
class KeptRow:
    """Something left in ``~/.carter`` because it is the user's: where, why, how many files."""

    path: Path
    reason: str
    count: int


@dataclass
class UninstallReport:
    """Everything ``uninstall`` did and left, as data."""

    code: int = 0  # 1 only when the guard step failed
    removed: dict[str, int] = field(default_factory=dict)  # kind -> count; see _kind
    edited_copies: list[tuple[Path, Path]] = field(default_factory=list)  # (agent, its copy)
    kept_files: list[Path] = field(default_factory=list)  # may hold edits: skills, AGENTS.md...
    mcp_servers: int = 0
    config_removed: bool = False  # config.toml held only defaults
    kept: list[KeptRow] = field(default_factory=list)
    manager: str = ""  # the command that removes the program itself
    leftover: bool = False  # ~/.carter still exists


def _remove_if_owned(
    path: Path,
    recorded: str | None,
    roots: tuple[Path, ...],
    opencode_base: Path,
    edited_copies: dict[Path, Path] | None = None,
) -> Status:
    """Delete a manifest file only if Carter still owns it, and say what happened.

    * Outside the managed roots (path-component check, not string prefix), or not a file →
      ``skipped``.
    * Recorded hash → delete only if the content still matches; else ``kept`` + warn.
    * No recorded hash → delete only ``carter-*``
      agent/skill files, which are Carter-owned by name. Knowledge files and
      ``AGENTS.md`` are user data and are ``kept``.
    * A global agent in ``edited_copies`` (edited since install, copied to ``backups/`` before
      the guards re-rendered it) is deleted whatever its hash says: ``edited-removed``.
    """
    resolved = path.resolve()
    if not path.is_file() or not _within(resolved, roots):
        return "skipped"
    edited = path in (edited_copies or {})
    if recorded is not None:
        if not edited and not _hash_matches(path, recorded):
            log_warn(f"Kept {tilde(path)}: edited since install")
            return "kept"
    else:
        base = opencode_base.resolve()
        owned_by_name = _within(resolved, (base / "agents", base / "skills")) and any(
            part.startswith("carter-") for part in resolved.relative_to(base).parts
        )
        if not owned_by_name:
            log_warn(f"Kept {tilde(path)}: no recorded hash to prove it is unmodified")
            return "kept"
    path.unlink()
    log_ok(f"Removed {tilde(path)}")
    # Drop now-empty carter-* skill directories (never agents/, skills/ or the roots).
    base = opencode_base.resolve()
    keep = (*roots, base / "agents", base / "skills")
    parent = resolved.parent
    while parent not in keep and _within(parent, roots) and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    return "edited-removed" if edited else "removed"


def _copy_edited_agents(
    manifest: dict, base_dir: Path | None, roots: tuple[Path, ...], opencode_base: Path
) -> dict[Path, Path]:
    """Copy the global agents the user edited into ``backups/<stamp>/``, before anything else
    runs: the guard step re-renders every agent and refreshes its recorded hash, so afterwards
    an edit can no longer be told from Carter's own output. Returns ``{agent: copy}``.

    Nothing has been removed yet, so a failed copy aborts the uninstall with the files intact."""
    agents = (opencode_base / "agents").resolve()
    hashes: dict[str, str] = manifest.get("file_hashes") or {}
    stamp_root = backups_dir(base_dir) / datetime.now(UTC).strftime(STAMP_FORMAT)
    copies: dict[Path, Path] = {}
    for listed in manifest.get("files", []):
        path, recorded = Path(listed), hashes.get(listed)
        if recorded is None or not path.is_file() or path.resolve().parent != agents:
            continue
        if _within(path.resolve(), roots) and not _hash_matches(path, recorded):
            _backup_file(path, stamp_root)
            copies[path] = stamp_root / _mirror(path)
    return copies


def _is_default_config(path: Path) -> bool:
    """True if ``config.toml`` holds nothing the user set: it parses to the all-defaults
    config (compared as a value, so a fully written older file counts too). A missing,
    unreadable or unknown-key file is not default."""
    try:
        return load_identity(path) == IdentityConfig(state="current")
    except ConfigError:
        return False


def _shipped_paths(base_dir: Path | None) -> list[Path]:
    """The agent and skill files this version of Carter installs, by name."""
    oc = _opencode_base(base_dir)
    agents = [oc / "agents" / name for name in _render_opencode_agents(base_dir)]
    skills = [
        oc / "skills" / d.name / f.name
        for d in sorted((REPO_ROOT / "skills").iterdir())
        if d.is_dir()
        for f in d.iterdir()
        if f.is_file()
    ]
    return agents + skills


def manager_command(executable: str | None = None) -> str:
    """The command that removes the program itself, read from where Python runs from."""
    where = (executable or sys.executable).replace("\\", "/")
    if "/uv/tools/" in where:
        return "uv tool uninstall carter-ai"
    if "/pipx/venvs/" in where:
        return "pipx uninstall carter-ai"
    if "/Cellar/" in where or "/homebrew/" in where:
        return "brew uninstall carter-ai"
    return "pip uninstall carter-ai"


def _kind(path: Path, opencode_base: Path, base_dir: Path | None) -> tuple[str, str]:
    """The report group of a removed file and the unit it counts as (a skill is a directory)."""
    p, oc = path.resolve(), opencode_base.resolve()
    if p.parent == oc / "agents":
        return "agents", p.name
    if p.is_relative_to(oc / "skills"):
        return "skills", p.relative_to(oc / "skills").parts[0]
    if p.is_relative_to(knowledge_dir(base_dir).resolve()):
        return "knowledge", p.name
    return ("AGENTS.md" if p.name == "AGENTS.md" else "other"), str(p)


def _rmdir_if_empty(path: Path) -> None:
    with contextlib.suppress(OSError):  # not empty, not a directory, gone: the user's or nothing
        path.rmdir()


def _count_files(root: Path) -> int:
    return sum(len(files) for _, _, files in os.walk(root))


def _clean_carter_home(base_dir: Path | None, report: UninstallReport) -> None:
    """Remove what Carter left in ``~/.carter`` that holds nothing of the user's: ``run/``
    (a cache), a ``config.toml`` that holds only defaults, and the empty directories Carter
    made. ``rmdir`` only ever removes an empty directory, so memories, edited knowledge,
    secrets, the audit log and backups stay by construction. Then list what stayed."""
    carter = _carter_base(base_dir)
    run = run_dir(base_dir)
    if os.path.lexists(run / "guard.log"):  # the move to state/audit/ failed: it is a log
        log_warn(f"Kept {tilde(run)}: guard.log could not be moved to state/audit/")
    elif run.is_symlink():
        run.unlink()
    elif run.is_dir():
        shutil.rmtree(run, ignore_errors=True)
    config = carter_config_path(base_dir)
    if config.is_file() and _is_default_config(config):
        config.unlink()
        report.config_removed = True
        log_ok(f"Removed {tilde(config)} (defaults only)")
    for sub in ("memories/user", "memories/session", "memories/repo", "memories", "knowledge"):
        _rmdir_if_empty(carter / sub)
    for sub in ("secrets", "state/audit", "state", "hooks", "bin", ""):
        _rmdir_if_empty(carter / sub)
    for rel, reason in _KEPT:
        count = _count_files(carter / rel) if (carter / rel).is_dir() else 0
        if count:
            report.kept.append(KeptRow(carter / rel, reason, count))
    if config.exists():
        report.kept.append(KeptRow(config, _KEPT_CONFIG, 1))
    report.leftover = carter.exists()


def uninstall(
    base_dir: Path | None, *, keep_guards: bool = False, assume_yes: bool = False
) -> UninstallReport:
    """Remove the OpenCode install and, unless ``keep_guards``, the guards (policies,
    per-agent denies, git config, guard state) that ``carter guard install`` wrote.

    The guards go first (policies before files), but a global agent the user edited is copied
    before that, while it can still be told from Carter's output. ``report.code`` is 1 if
    removing the guards failed; everything else is still removed, as ``carter install`` never
    aborts on its guard step."""
    set_verbosity(2 if ui.verbose() else 1)  # -v lists every file removed or kept
    log_step("Uninstalling Carter...")
    from carter.guard.hooks import migrate_guard_log

    report = UninstallReport(manager=manager_command())
    migrate_guard_log(base_dir)  # a log an older guard script left in run/ is kept, in state/audit/
    opencode_base = _opencode_base(base_dir)
    managed_roots = _managed_roots(base_dir)
    first = read_manifest(base_dir)
    copies = _copy_edited_agents(first, base_dir, managed_roots, opencode_base) if first else {}
    if not keep_guards:
        from carter.guard.wiring import uninstall_guards, uninstall_identity

        report.code = uninstall_guards(base_dir, assume_yes=assume_yes)
        uninstall_identity(base_dir, assume_yes=assume_yes)  # independent of the guards
    manifest = read_manifest(base_dir)  # the guard step re-wrote it

    if manifest:
        hashes: dict[str, str] = manifest.get("file_hashes") or {}
        listed = [(Path(f), hashes.get(f)) for f in manifest.get("files", [])]
    else:
        # No manifest: the files this version ships, by name; never by prefix, never a tree.
        listed = [(p, None) for p in _shipped_paths(base_dir)]
    units: dict[str, set[str]] = {}
    for path, recorded in listed:
        status = _remove_if_owned(path, recorded, managed_roots, opencode_base, copies)
        if status == "kept":
            report.kept_files.append(path)
        elif status != "skipped":
            kind, unit = _kind(path, opencode_base, base_dir)
            units.setdefault(kind, set()).add(unit)
        if status == "edited-removed":
            log_warn(
                f"Removed {tilde(path)} although you edited it",
                f"copy: {tilde(copies[path])}",
            )
            report.edited_copies.append((path, copies[path]))
    report.removed = {kind: len(found) for kind, found in units.items()}

    log_step("Removing MCP servers (OpenCode)...")
    servers: set[str] = set()
    for cfg in global_config_files(base_dir):
        removed = remove_carter_servers(cfg)
        for name in removed:
            servers.add(name)
            log_ok(f"Removed {name} from {cfg.name}")
        if removed and _is_empty_json(cfg):
            cfg.unlink()  # a file only Carter's servers were in
            log_ok(f"Removed {cfg.name} (empty)")
    report.mcp_servers = len(servers)

    # Remove manifest
    path = manifest_path(base_dir)
    if path.exists():
        path.unlink()
        log_ok("Removed manifest")

    _clean_carter_home(base_dir, report)
    ui.ok("uninstalled")
    return report


def _is_empty_json(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")) == {}
    except (OSError, ValueError):
        return False
