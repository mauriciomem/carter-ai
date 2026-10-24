"""Carter system-level installer (public entry point).

Installs Carter agents, skills, instructions, knowledge base, and MCP server
configurations for VS Code Copilot, Copilot CLI, and OpenCode.

This module backs the ``carter install`` command. The implementation was split
into the ``carter.install`` package; this module imports those leaves and keeps the
orchestration plus the few helpers that tests monkeypatch through this namespace
(``_vscode_detected``, ``_vscode_settings_path``, ``check_prerequisites``,
``configure_mcp_servers`` — each resolves a patched dependency from this module's
globals). Data files are resolved via ``carter.resources.data_dir()`` so it works
both from a development checkout and from an installed wheel (``uv tool install``).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from carter import __version__
from carter.config import resolve_targets
from carter.install.components import (
    install_agents,
    install_instructions,
    install_knowledge,
    install_memories,
    install_opencode_rules,
    install_ops,
    install_skills,
    read_manifest,
    write_manifest,
)
from carter.install.console import (
    _log,
    bold,
    green,
    log_debug,
    log_ok,
    log_skip,
    log_step,
    log_warn,
    set_verbosity,
)
from carter.install.mcp import MCP_SERVERS, _merge_json_key
from carter.install.paths import (
    REPO_ROOT,
    _copilot_base,
    _home,
    _opencode_base,
    _vscode_user_dirs,
)
from carter.install.prereqs import _cmd_version, _which, check_credentials, detect_environment
from carter.install.uninstall import uninstall

# ──────────────────────────────────────────────────────────────────────────────
# VS Code path detection (kept here so `_vscode_user_dirs` resolves through this
# module's namespace — tests monkeypatch `installer._vscode_user_dirs`)
# ──────────────────────────────────────────────────────────────────────────────


def _vscode_settings_path(base_dir: Path | None) -> Path:
    """Return the VS Code ``settings.json`` to read/write.

    Prefers the first candidate whose ``User/`` directory already exists (so an
    Insiders/VSCodium/Flatpak install is targeted correctly); otherwise falls
    back to the first candidate (the stable default), preserving prior behavior.
    """
    candidates = _vscode_user_dirs(base_dir)
    for user_dir in candidates:
        if user_dir.is_dir():
            return user_dir / "settings.json"
    return candidates[0] / "settings.json"


def _vscode_detected(base_dir: Path | None) -> bool:
    """Whether a VS Code user config directory exists (so writing settings is safe).

    Always True under ``base_dir`` (test mode). Otherwise True only if one of the
    known variant ``User/`` directories is present — avoids creating a phantom
    ``settings.json`` VS Code will never read when it isn't installed.
    """
    if base_dir:
        return True
    return any(user_dir.is_dir() for user_dir in _vscode_user_dirs(base_dir))


# ──────────────────────────────────────────────────────────────────────────────
# Prerequisite checks (kept here so `_which` resolves through this namespace)
# ──────────────────────────────────────────────────────────────────────────────


def check_prerequisites(targets: list[str]) -> dict[str, bool]:
    log_step("Checking prerequisites...")
    checks: dict[str, bool] = {}

    # Tools the install integrates with. None are required for a successful
    # install — they enable optional features (VS Code MCP, the Copilot/OpenCode
    # CLIs, and `gh`-based carter-ops). `jq`/`terraform` are NOT install prereqs
    # (the installer uses Python's json; terraform is unrelated to installing).
    tools = [
        ("VS Code", "code", False),
        ("gh CLI", "gh", True),
    ]

    if "copilot" in targets:
        tools.append(("copilot CLI", "copilot", False))
    if "opencode" in targets:
        tools.append(("opencode", "opencode", False))

    for label, cmd, optional in tools:
        found = _which(cmd)
        version = _cmd_version(cmd, "--version") if found else None
        ver_str = version.split("\n")[0][:30] if version else ""

        if found:
            log_ok(label, ver_str)
            checks[cmd] = True
        elif optional:
            log_warn(f"{label} not found (optional)")
            checks[cmd] = False
        else:
            log_warn(f"{label} not found")
            checks[cmd] = False

    return checks


# ──────────────────────────────────────────────────────────────────────────────
# MCP server configuration (kept here so `_vscode_detected` resolves through this
# namespace — tests monkeypatch `installer._vscode_detected`)
# ──────────────────────────────────────────────────────────────────────────────


def configure_mcp_servers(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    prereqs: dict[str, bool],
    backup_root: Path | None = None,
    servers: list[str] | None = None,
) -> int:
    """Wire the selected MCP servers into each target's config.

    ``servers`` is the opt-in selection (RFC-0004 lever 1): a subset of ``MCP_SERVERS``.
    ``None`` (the default) means the full shipped set — today's backward-compatible
    behaviour, so an unused server can be dropped per workspace without adding its
    tool-schema tokens. An unknown server name is a ``ValueError``.
    """
    log_step("Configuring MCP servers...")
    count = 0
    if servers is None:
        servers = list(MCP_SERVERS)
    else:
        unknown = [s for s in servers if s not in MCP_SERVERS]
        if unknown:
            raise ValueError(
                f"Unknown MCP server(s): {', '.join(unknown)}. "
                f"Choose from: {', '.join(MCP_SERVERS)}."
            )
        servers = list(servers)

    if "copilot" in targets:
        # VS Code settings.json — only when a VS Code config dir actually exists,
        # so we never create a phantom settings.json that VS Code won't read.
        if _vscode_detected(base_dir):
            vscode_settings = _vscode_settings_path(base_dir)
            copilot_entries = {}
            for server in servers:
                src = REPO_ROOT / "mcp" / "copilot" / f"{server}.json"
                copilot_entries.update(json.loads(src.read_text()))

            _merge_json_key(vscode_settings, "mcp.servers", copilot_entries, backup_root)
            for server in servers:
                log_ok(f"carter-{server} → VS Code settings.json")
                count += 1
        else:
            log_skip("VS Code not detected — skipping settings.json (use the CLI targets)")

        # Copilot CLI via `copilot mcp add`
        if prereqs.get("copilot", False) and not base_dir:
            for server in servers:
                src = REPO_ROOT / "mcp" / "copilot" / f"{server}.json"
                config = json.loads(src.read_text())
                name = f"carter-{server}"
                entry = config[name]

                cmd_parts = [entry["command"]] + entry.get("args", [])
                env_args = []
                for k, v in entry.get("env", {}).items():
                    env_val = os.environ.get(k, v)
                    env_args.extend(["--env", f"{k}={env_val}"])

                try:
                    # Remove first if exists (idempotent)
                    subprocess.run(
                        ["copilot", "mcp", "remove", name],
                        capture_output=True,
                        timeout=10,
                    )
                    subprocess.run(
                        ["copilot", "mcp", "add", name] + env_args + ["--"] + cmd_parts,
                        capture_output=True,
                        timeout=10,
                        check=True,
                    )
                    log_ok(f"{name} → copilot mcp add")
                    count += 1
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    log_warn(f"Failed to add {name} to Copilot CLI: {e}")
        elif not base_dir:
            log_skip("copilot CLI not found, skipping copilot mcp add")

    if "opencode" in targets:
        opencode_config = _opencode_base(base_dir) / "opencode.json"
        opencode_entries = {}
        for server in servers:
            src = REPO_ROOT / "mcp" / "opencode" / f"{server}.json"
            opencode_entries.update(json.loads(src.read_text()))

        _merge_json_key(opencode_config, "mcp", opencode_entries, backup_root)
        for server in servers:
            log_ok(f"carter-{server} → opencode.json")
            count += 1

    manifest["mcp_servers"] = [f"carter-{s}" for s in servers]
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────────


def run(
    target: str = "all",
    mcp: bool = False,
    bot_name: str = "carter-bot",
    uninstall_flag: bool = False,
    base_dir: Path | None = None,
    verbosity: int = 1,
    mcp_servers: list[str] | None = None,
) -> None:
    """Run the Carter system-level install (or uninstall).

    This is the programmatic entry point used by the ``carter install``
    command. Parameters mirror the CLI options. ``mcp_servers`` is the opt-in
    subset (RFC-0004 lever 1); ``None`` installs the full shipped set.
    """
    set_verbosity(verbosity)

    targets = resolve_targets(target)

    _log(f"\n {bold('Carter Installer')}")
    _log(f" Target: {', '.join(targets)}")
    _log(f" Bot name: {bot_name}")
    _mcp_label = "no (use --mcp to install)"
    if mcp:
        _mcp_label = "yes" + (f" ({', '.join(mcp_servers)})" if mcp_servers else " (all)")
    _log(f" MCP servers: {_mcp_label}")

    detect_environment()
    prereqs = check_prerequisites(targets)

    if uninstall_flag:
        uninstall(targets, base_dir, prereqs)
        return

    if mcp:
        check_credentials()
    else:
        log_step("Skipping MCP credentials (no --mcp flag)")

    now = datetime.now(UTC)
    backup_root = _copilot_base(base_dir) / "backup" / now.strftime("%Y%m%dT%H%M%S")

    manifest: dict = {
        "version": __version__,
        "installed_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "targets": targets,
        "files": [],
        "mcp_servers": [],
        "file_hashes": {},
    }

    # Check for existing manifest (update scenario)
    existing = read_manifest(base_dir)
    if existing:
        manifest["installed_at"] = existing.get("installed_at", now.isoformat())
        log_debug("Existing installation found — updating")

    # Install components
    agent_stats = install_agents(targets, base_dir, manifest, backup_root)
    skill_stats = install_skills(targets, base_dir, manifest, backup_root, bot_name=bot_name)
    install_instructions(targets, base_dir, manifest, backup_root)
    install_opencode_rules(targets, base_dir, manifest, backup_root)
    knowledge_count = install_knowledge(base_dir, manifest, backup_root)
    memory_count = install_memories(base_dir, manifest)
    ops_stats = install_ops(base_dir, manifest, backup_root, bot_name=bot_name)

    if mcp:
        mcp_count = configure_mcp_servers(
            targets, base_dir, manifest, prereqs, backup_root, servers=mcp_servers
        )
    else:
        log_step("Skipping MCP servers (no --mcp flag)")
        mcp_count = 0
        manifest["mcp_servers"] = []

    # Write manifest
    manifest_path = write_manifest(manifest, base_dir)

    # Summary
    total_agents = agent_stats["created"] + agent_stats["updated"] + agent_stats["unchanged"]
    total_skills = skill_stats["created"] + skill_stats["updated"] + skill_stats["unchanged"]
    total_ops = ops_stats["created"] + ops_stats["updated"] + ops_stats["unchanged"]

    _log(f"\n{green('✓')} {bold('Installation complete')}")
    _log(f"  Agents: {total_agents}")
    _log(f"  Skills: {total_skills}")
    _log(f"  Ops config: {total_ops}")
    _log(f"  MCP servers: {mcp_count}")
    _log(f"  Knowledge files: {knowledge_count} new")
    _log(f"  Memory dirs: {memory_count} new")
    _log(f"  Manifest: {str(manifest_path).replace(str(_home()), '~')}")

    # Show update stats if relevant
    updated = agent_stats["updated"] + skill_stats["updated"]
    unchanged = agent_stats["unchanged"] + skill_stats["unchanged"]
    if updated > 0 or unchanged > 0:
        _log(
            f"  Changes: {agent_stats['created'] + skill_stats['created']} created, "
            f"{updated} updated, {unchanged} unchanged",
            level=2,
        )
