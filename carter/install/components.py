"""Component installers: agents, skills, instructions, knowledge, memories, ops.

Plus the install manifest read/write. These are pure orchestration over the file
primitives and path resolvers — none are monkeypatched by tests, so they live here
rather than in ``carter.installer``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from carter.install.console import log_ok, log_skip, log_step
from carter.install.files import _get_template_vars, _install_file, _install_templated_file
from carter.install.paths import (
    REPO_ROOT,
    _carter_base,
    _copilot_base,
    _home,
    _opencode_base,
)


def install_agents(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> dict[str, int]:
    log_step("Installing agents...")
    src_dir = REPO_ROOT / "agents"
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}

    for agent_file in sorted(src_dir.glob("carter-*.md")):
        if "copilot" in targets:
            dst = _copilot_base(base_dir) / "agents" / agent_file.name
            status = _install_file(agent_file, dst, manifest, backup_root)
            stats[status] += 1

        if "opencode" in targets:
            dst = _opencode_base(base_dir) / "agents" / agent_file.name
            status = _install_file(agent_file, dst, manifest, backup_root)
            stats[status] += 1

    return stats


def install_skills(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
    bot_name: str = "carter-bot",
) -> dict[str, int]:
    log_step("Installing skills...")
    src_dir = REPO_ROOT / "skills"
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}

    # Load config for template substitution (carter-ops SKILL.md)
    carter_home = _carter_base(base_dir)
    config_path = carter_home / "config.toml"
    template_vars = _get_template_vars(config_path, bot_name)

    for skill_dir in sorted(src_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        skill_files = [f for f in sorted(skill_dir.iterdir()) if f.is_file()]
        for src_file in skill_files:
            rel = src_file.relative_to(skill_dir)

            # Template substitution for carter-ops SKILL.md
            needs_template = skill_dir.name == "carter-ops" and src_file.name == "SKILL.md"

            if "copilot" in targets:
                dst = _copilot_base(base_dir) / "skills" / skill_dir.name / rel
                if needs_template:
                    status = _install_templated_file(
                        src_file, dst, manifest, backup_root, template_vars
                    )
                else:
                    status = _install_file(src_file, dst, manifest, backup_root)
                stats[status] += 1

            if "opencode" in targets:
                dst = _opencode_base(base_dir) / "skills" / skill_dir.name / rel
                if needs_template:
                    status = _install_templated_file(
                        src_file, dst, manifest, backup_root, template_vars
                    )
                else:
                    status = _install_file(src_file, dst, manifest, backup_root)
                stats[status] += 1

    return stats


def install_instructions(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> None:
    log_step("Installing instructions...")
    src = REPO_ROOT / "instructions" / "copilot-instructions.md"

    if "copilot" in targets:
        dst = _copilot_base(base_dir) / "instructions" / "copilot-instructions.md"
        _install_file(src, dst, manifest, backup_root)

    if "opencode" in targets:
        dst = _opencode_base(base_dir) / "instructions" / "copilot-instructions.md"
        _install_file(src, dst, manifest, backup_root)


_OPENCODE_AGENTS_MD = """\
# Carter — Global Rules

When the user's request starts with `ops:`, load the `carter-ops` skill and follow
its instructions exactly.

## Memory
- Record mistakes and key learnings to `~/.carter/memories/` (visible) and
  `/memories/` (platform, if available).
- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for
  project-specific notes, and `session/` for conversation-scoped working notes.
- Consult `~/.carter/memories/` and `~/.copilot/knowledge/` before proposing
  solutions to check for past decisions and lessons.
"""


def install_opencode_rules(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> None:
    """Generate ~/.config/opencode/AGENTS.md for OpenCode global rules."""
    if "opencode" not in targets:
        return
    log_step("Installing OpenCode global rules...")
    dst = _opencode_base(base_dir) / "AGENTS.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        log_skip(f"{str(dst).replace(str(_home()), '~')} (exists, not overwriting)")
        manifest["files"].append(str(dst))
    else:
        dst.write_text(_OPENCODE_AGENTS_MD)
        log_ok(str(dst).replace(str(_home()), "~"))
        manifest["files"].append(str(dst))


def install_memories(
    base_dir: Path | None,
    manifest: dict,
) -> int:
    """Create ~/.carter/memories/ directory structure."""
    log_step("Initializing memory directories...")
    memories_dir = _carter_base(base_dir) / "memories"
    count = 0

    for scope in ("user", "session", "repo"):
        scope_dir = memories_dir / scope
        if scope_dir.exists():
            log_skip(f"{str(scope_dir).replace(str(_home()), '~')} (exists)")
        else:
            scope_dir.mkdir(parents=True, exist_ok=True)
            log_ok(str(scope_dir).replace(str(_home()), "~"))
            count += 1
        manifest["files"].append(str(scope_dir))

    return count


def install_knowledge(
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> int:
    log_step("Initializing knowledge base...")
    src_dir = REPO_ROOT / "knowledge"
    dst_dir = _copilot_base(base_dir) / "knowledge"
    count = 0

    for src_file in sorted(src_dir.glob("*.md")):
        dst = dst_dir / src_file.name
        if dst.exists():
            log_skip(f"{str(dst).replace(str(_home()), '~')} (exists, not overwriting)")
            manifest["files"].append(str(dst))
        else:
            _install_file(src_file, dst, manifest, backup_root)
            count += 1

    return count


def install_ops(
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
    bot_name: str = "carter-bot",
) -> dict[str, int]:
    """Generate carter-ops configuration.

    The ``carter ops`` subcommand ships with the installed ``carter`` CLI, so
    no source files or wrapper scripts need to be copied. This only generates
    ``~/.carter/config.toml`` (non-secret attribution + git settings) if it
    does not already exist.
    """
    log_step("Configuring carter-ops...")
    carter_home = _carter_base(base_dir)
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}

    config_path = carter_home / "config.toml"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Auto-detect signing key
        signing_key = ""
        try:
            result = subprocess.run(
                ["git", "config", "user.signingkey"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                signing_key = result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        bot_email = f"{bot_name}@users.noreply.github.com"
        config_content = (
            "[attribution]\n"
            f'name = "{bot_name}"\n'
            f'email = "{bot_email}"\n'
            f'footer = "This comment was generated by {bot_name}."\n'
            "\n"
            "[git]\n"
            f'signing_key = "{signing_key}"\n'
            "\n"
            "[jira]\n"
            'url = ""\n'
            'email = ""\n'
            "# token comes from JIRA_TOKEN or ATLASSIAN_API_TOKEN env var — never in config file\n"
        )
        config_path.write_text(config_content)
        log_ok(f"{str(config_path).replace(str(_home()), '~')}")
        manifest["files"].append(str(config_path))
        stats["created"] += 1
    else:
        log_skip(f"{str(config_path).replace(str(_home()), '~')} (exists, not overwriting)")
        stats["unchanged"] += 1

    return stats


def write_manifest(manifest: dict, base_dir: Path | None) -> Path:
    manifest_path = _copilot_base(base_dir) / ".carter-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest_path


def read_manifest(base_dir: Path | None) -> dict | None:
    manifest_path = _copilot_base(base_dir) / ".carter-manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return None
