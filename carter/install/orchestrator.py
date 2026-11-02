"""``carter install`` orchestration (OpenCode-only).

Order matters: ``require_opencode`` runs before anything is written, so an
unsupported or missing OpenCode fails the install hard with nothing on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from carter import __version__
from carter.home import tilde
from carter.install.components import (
    install_agents,
    install_knowledge,
    install_memories,
    install_opencode_rules,
    install_ops,
    install_skills,
    read_manifest,
    remove_retired_skills,
    write_manifest,
)
from carter.install.console import _log, bold, green, log_debug, log_step, set_verbosity
from carter.install.mcp import configure_mcp_servers
from carter.install.paths import backups_dir
from carter.install.prereqs import (
    check_credentials,
    check_optional_tools,
    detect_environment,
    require_opencode,
)


def run(
    mcp: bool = False,
    base_dir: Path | None = None,
    verbosity: int = 1,
    mcp_servers: list[str] | None = None,
    *,
    guards: bool = False,
    assume_yes: bool = False,
) -> int:
    """Run the Carter system-level install for OpenCode.

    Parameters mirror the ``carter install`` options. ``mcp_servers`` is the
    opt-in subset; ``None`` installs the full shipped set. With ``guards`` the install ends
    by running ``carter guard install`` (consented policies; a non-TTY run without
    ``assume_yes`` skips it with a notice). A guard failure is printed and returned as 1; it
    never undoes or aborts the rest of the install.

    Raises:
        PrerequisiteError: OpenCode is missing or older than 2.1.
    """
    set_verbosity(verbosity)

    _log(f"\n {bold('Carter Installer')}")
    _mcp_label = "no (use --mcp to install)"
    if mcp:
        _mcp_label = "yes" + (f" ({', '.join(mcp_servers)})" if mcp_servers else " (all)")
    _log(f" MCP servers: {_mcp_label}")

    detect_environment()
    log_step("Checking prerequisites...")
    require_opencode()
    check_optional_tools()

    if mcp:
        check_credentials(base_dir)
    else:
        log_step("Skipping MCP credentials (no --mcp flag)")

    now = datetime.now(UTC)
    backup_root = backups_dir(base_dir) / now.strftime("%Y%m%dT%H%M%S")

    manifest: dict = {
        "version": __version__,
        "installed_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "files": [],
        "mcp_servers": [],
        "file_hashes": {},
    }

    existing = read_manifest(base_dir)
    if existing:
        manifest["installed_at"] = existing.get("installed_at", now.isoformat())
        log_debug("Existing installation found — updating")

    agent_stats = install_agents(base_dir, manifest, backup_root)
    skill_stats = install_skills(base_dir, manifest, backup_root)
    remove_retired_skills(base_dir, existing, backup_root)
    install_opencode_rules(base_dir, manifest, existing)
    knowledge_count = install_knowledge(base_dir, manifest, backup_root)
    memory_count = install_memories(base_dir, manifest)
    ops_created = install_ops(base_dir, manifest)

    if mcp:
        mcp_count = configure_mcp_servers(base_dir, manifest, backup_root, servers=mcp_servers)
    else:
        log_step("Skipping MCP servers (no --mcp flag)")
        mcp_count = 0

    manifest_path = write_manifest(manifest, base_dir)

    total_agents = agent_stats["created"] + agent_stats["updated"] + agent_stats["unchanged"]

    _log(f"\n{green('✓')} {bold('Installation complete')}")
    _log(f"  Agents: {total_agents}")
    _log(f"  Skills: {skill_stats['skills']}")
    _log(f"  Ops config: {'created or migrated' if ops_created else 'kept'}")
    _log(f"  MCP servers: {mcp_count}")
    _log(f"  Knowledge files: {knowledge_count} new")
    _log(f"  Memory dirs: {memory_count} new")
    _log(f"  Manifest: {tilde(manifest_path)}")

    updated = agent_stats["updated"] + skill_stats["updated"]
    unchanged = agent_stats["unchanged"] + skill_stats["unchanged"]
    if updated > 0 or unchanged > 0:
        _log(
            f"  Changes: {agent_stats['created'] + skill_stats['created']} created, "
            f"{updated} updated, {unchanged} unchanged",
            level=2,
        )

    if not guards:
        return 0
    from carter.guard.wiring import install_guards

    return install_guards(base_dir, assume_yes=assume_yes)
