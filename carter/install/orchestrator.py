"""``carter install`` orchestration (OpenCode-only, ADR-0014).

Order matters: ``require_opencode`` runs before anything is written, so an
unsupported or missing OpenCode fails the install hard with nothing on disk (D6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from carter import __version__
from carter.install.components import (
    install_agents,
    install_knowledge,
    install_memories,
    install_opencode_rules,
    install_ops,
    install_skills,
    read_manifest,
    remove_legacy_opencode_instructions,
    write_manifest,
)
from carter.install.console import _log, bold, green, log_debug, log_step, set_verbosity
from carter.install.legacy import warn_legacy_copilot
from carter.install.mcp import configure_mcp_servers
from carter.install.paths import _copilot_base, _home
from carter.install.prereqs import (
    check_credentials,
    check_optional_tools,
    detect_environment,
    require_opencode,
)
from carter.install.uninstall import uninstall


def run(
    mcp: bool = False,
    bot_name: str = "carter-bot",
    uninstall_flag: bool = False,
    base_dir: Path | None = None,
    verbosity: int = 1,
    mcp_servers: list[str] | None = None,
) -> None:
    """Run the Carter system-level install (or uninstall) for OpenCode.

    Parameters mirror the ``carter install`` options. ``mcp_servers`` is the
    opt-in subset; ``None`` installs the full shipped set.

    Raises:
        PrerequisiteError: OpenCode is missing or older than 2.1 (install only).
    """
    set_verbosity(verbosity)

    _log(f"\n {bold('Carter Installer')}")
    _log(f" Bot name: {bot_name}")
    _mcp_label = "no (use --mcp to install)"
    if mcp:
        _mcp_label = "yes" + (f" ({', '.join(mcp_servers)})" if mcp_servers else " (all)")
    _log(f" MCP servers: {_mcp_label}")

    if uninstall_flag:
        uninstall(base_dir)
        return

    detect_environment()
    log_step("Checking prerequisites...")
    require_opencode()
    check_optional_tools()
    warn_legacy_copilot(base_dir)

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
        "targets": ["opencode"],
        "files": [],
        "mcp_servers": [],
        "file_hashes": {},
    }

    existing = read_manifest(base_dir)
    if existing:
        manifest["installed_at"] = existing.get("installed_at", now.isoformat())
        log_debug("Existing installation found — updating")

    agent_stats = install_agents(base_dir, manifest, backup_root)
    skill_stats = install_skills(base_dir, manifest, backup_root, bot_name=bot_name)
    # OpenCode reads AGENTS.md; drop the instructions copy older versions wrote.
    remove_legacy_opencode_instructions(base_dir, backup_root)
    install_opencode_rules(base_dir, manifest, backup_root)
    knowledge_count = install_knowledge(base_dir, manifest, backup_root)
    memory_count = install_memories(base_dir, manifest)
    ops_stats = install_ops(base_dir, manifest, backup_root, bot_name=bot_name)

    if mcp:
        mcp_count = configure_mcp_servers(base_dir, manifest, backup_root, servers=mcp_servers)
    else:
        log_step("Skipping MCP servers (no --mcp flag)")
        mcp_count = 0

    manifest_path = write_manifest(manifest, base_dir)

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

    updated = agent_stats["updated"] + skill_stats["updated"]
    unchanged = agent_stats["unchanged"] + skill_stats["unchanged"]
    if updated > 0 or unchanged > 0:
        _log(
            f"  Changes: {agent_stats['created'] + skill_stats['created']} created, "
            f"{updated} updated, {unchanged} unchanged",
            level=2,
        )
