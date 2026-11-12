"""Carter uninstall — manifest-driven removal; without a manifest, the files this version ships."""

from __future__ import annotations

from pathlib import Path

from carter import ui
from carter.home import tilde
from carter.identity import ConfigError, load_identity
from carter.identity.schema import IdentityConfig
from carter.install.components import _render_opencode_agents, read_manifest
from carter.install.console import log_ok, log_step, log_warn
from carter.install.mcp import global_config_files, remove_carter_servers
from carter.install.ownership import _hash_matches, _within
from carter.install.paths import (
    REPO_ROOT,
    _opencode_base,
    manifest_path,
)
from carter.install.paths import (
    managed_roots as _managed_roots,
)


def _remove_if_owned(
    path: Path, recorded: str | None, roots: tuple[Path, ...], opencode_base: Path
) -> None:
    """Delete a manifest file only if Carter still owns it.

    * Outside the managed roots (path-component check, not string prefix) → ignored.
    * Recorded hash → delete only if the content still matches; else keep + warn.
    * No recorded hash → delete only ``carter-*``
      agent/skill files, which are Carter-owned by name. Knowledge files and
      ``AGENTS.md`` are user data and are kept.
    """
    resolved = path.resolve()
    if not path.is_file() or not _within(resolved, roots):
        return
    if recorded is not None:
        if not _hash_matches(path, recorded):
            log_warn(f"Kept {tilde(path)}: edited since install")
            return
    else:
        base = opencode_base.resolve()
        owned_by_name = _within(resolved, (base / "agents", base / "skills")) and any(
            part.startswith("carter-") for part in resolved.relative_to(base).parts
        )
        if not owned_by_name:
            log_warn(f"Kept {tilde(path)}: no recorded hash to prove it is unmodified")
            return
    path.unlink()
    log_ok(f"Removed {tilde(path)}")
    # Drop now-empty carter-* skill directories (never agents/, skills/ or the roots).
    base = opencode_base.resolve()
    keep = (*roots, base / "agents", base / "skills")
    parent = resolved.parent
    while parent not in keep and _within(parent, roots) and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


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


def uninstall(base_dir: Path | None, *, keep_guards: bool = False, assume_yes: bool = False) -> int:
    """Remove the OpenCode install and, unless ``keep_guards``, the guards (policies,
    per-agent denies, git config, guard state) that ``carter guard install`` wrote.

    The guards go first (policies before files). Returns 1 if removing the guards failed;
    everything else is still removed, as ``carter install`` never aborts on its guard step."""
    log_step("Uninstalling Carter...")
    guard_code = 0
    if not keep_guards:
        from carter.guard.wiring import uninstall_guards, uninstall_identity

        guard_code = uninstall_guards(base_dir, assume_yes=assume_yes)
        uninstall_identity(base_dir, assume_yes=assume_yes)  # independent of the guards
    manifest = read_manifest(base_dir)
    opencode_base = _opencode_base(base_dir)
    managed_roots = _managed_roots(base_dir)

    if manifest:
        hashes: dict[str, str] = manifest.get("file_hashes") or {}
        for f in manifest.get("files", []):
            _remove_if_owned(Path(f), hashes.get(f), managed_roots, opencode_base)
    else:
        # No manifest: the files this version ships, by name; never by prefix, never a tree.
        for p in _shipped_paths(base_dir):
            _remove_if_owned(p, None, managed_roots, opencode_base)

    log_step("Removing MCP servers (OpenCode)...")
    for cfg in global_config_files(base_dir):
        for name in remove_carter_servers(cfg):
            log_ok(f"Removed {name} from {cfg.name}")

    # Remove manifest
    path = manifest_path(base_dir)
    if path.exists():
        path.unlink()
        log_ok("Removed manifest")

    ui.ok("uninstalled")
    return guard_code
