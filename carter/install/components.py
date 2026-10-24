"""Component installers: agents, skills, instructions, knowledge, memories, ops.

Plus the install manifest read/write. These are pure orchestration over the file
primitives and path resolvers — none are monkeypatched by tests, so they live here
rather than in ``carter.installer``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from carter.install.console import log_ok, log_skip, log_step, log_warn
from carter.install.files import (
    _get_template_vars,
    _install_file,
    _install_rendered_file,
    _install_templated_file,
    _sha256,
)
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

    # The static `agents/*.md` are copilot-shaped (a `tools:` allowlist array).
    # OpenCode rejects that array — it wants a `permission` block and `provider/model`
    # ids — so for the opencode target we render the OpenCode-shaped frontmatter from
    # the guarded defaults rather than copying the copilot file verbatim.
    opencode_rendered = _render_opencode_agents() if "opencode" in targets else {}

    for agent_file in sorted(src_dir.glob("carter-*.md")):
        if "copilot" in targets:
            dst = _copilot_base(base_dir) / "agents" / agent_file.name
            status = _install_file(agent_file, dst, manifest, backup_root)
            stats[status] += 1

        if "opencode" in targets:
            dst = _opencode_base(base_dir) / "agents" / agent_file.name
            content = opencode_rendered[agent_file.name]
            status = _install_rendered_file(content, dst, manifest, backup_root)
            stats[status] += 1

    return stats


def _render_opencode_agents() -> dict[str, str]:
    """Render the OpenCode-shaped agent files from the shipped guarded defaults.

    Returns ``{filename: content}`` keyed by ``carter-<role>.md`` (no agent suffix —
    global installs use canonical names). Imported lazily so the install path does
    not pull in the scaffold/Jinja stack unless an opencode target is requested.
    """
    from carter.config import generate_default_config
    from carter.scaffold import create_env, render_agents

    cfg = generate_default_config(workspace_name="carter", mode="single")
    cfg["target"] = "opencode"
    cfg["agent_suffix"] = ""
    return render_agents(cfg, create_env())


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

    # OpenCode never loads instructions/copilot-instructions.md (it reads AGENTS.md,
    # installed by install_opencode_rules), so it is no longer copied there. Clean up
    # the copy earlier Carter versions wrote, so upgrades don't leave it behind.
    if "opencode" in targets:
        remove_legacy_opencode_instructions(base_dir, backup_root)


def remove_legacy_opencode_instructions(base_dir: Path | None, backup_root: Path | None) -> None:
    """Remove the OpenCode copy of copilot-instructions.md older Carter versions wrote.

    Deleted only when it is provably Carter-owned: its hash equals the shipped file,
    or the existing install manifest recorded it with the same hash. Otherwise it is
    treated as user-modified: moved to ``backup_root`` when given, else left in place
    with a warning. A symlink is never followed or removed.
    """
    stale = _opencode_base(base_dir) / "instructions" / "copilot-instructions.md"
    shown = str(stale).replace(str(_home()), "~")
    if stale.is_symlink():
        log_warn(f"{shown} is a symlink — left untouched (no longer used by OpenCode)")
        return
    if not stale.is_file():
        return

    current = _sha256(stale)
    shipped = REPO_ROOT / "instructions" / "copilot-instructions.md"
    recorded = ((read_manifest(base_dir) or {}).get("file_hashes") or {}).get(str(stale))
    carter_owned = current == _sha256(shipped) or current == recorded

    if carter_owned:
        stale.unlink()
        log_ok(f"Removed stale {shown}")
    elif backup_root is not None:
        dest = backup_root / "opencode-instructions" / stale.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stale), dest)
        log_warn(
            f"{shown} was modified — moved to {str(dest).replace(str(_home()), '~')} "
            "(OpenCode does not load it)"
        )
    else:
        log_warn(f"{shown} was modified — left in place (OpenCode does not load it)")
        return

    parent = stale.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


_OPENCODE_AGENTS_MD_LEGACY = """\
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

# Ported verbatim from instructions/copilot-instructions.md §Communication (D2: only
# this section — AGENTS.md loads every session, so token cost is disciplined). Written
# as implicit concatenation purely to satisfy the line-length lint; the emitted bytes
# match the instructions file exactly.
_OPENCODE_COMMUNICATION = (
    "\n## Communication\n"
    "- Be concise and clear. Explain so a junior developer or solution architect"
    " understands.\n"
    "- Cite sources. State which documentation, standards, or references inform your"
    " answers.\n"
    "- When reviewing, match detail to the change (quick vs deep), comment on the code"
    " not the author, and explain *why* behind each finding. See `carter-code-review`.\n"
    "- At any doubt, ask for clarification before proceeding.\n"
)

_OPENCODE_AGENTS_MD = _OPENCODE_AGENTS_MD_LEGACY + _OPENCODE_COMMUNICATION


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
    shown = str(dst).replace(str(_home()), "~")
    if not dst.exists():
        dst.write_text(_OPENCODE_AGENTS_MD)
        log_ok(shown)
    elif dst.read_text() == _OPENCODE_AGENTS_MD_LEGACY:
        # Unmodified legacy content (hash-idempotency philosophy): safe to upgrade.
        dst.write_text(_OPENCODE_AGENTS_MD)
        log_ok(f"{shown} (upgraded: added Communication section)")
    elif dst.read_text() == _OPENCODE_AGENTS_MD:
        log_skip(f"{shown} (already current)")
    else:
        # User-modified — NEVER clobber.
        log_warn(
            f"{shown} (user-modified, skipping)", hint="merge the Communication section manually"
        )
        manifest.setdefault("notes", []).append(
            f"{shown}: user-modified, Communication section not installed"
        )
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
            "# Co-author identity: credited via a `Co-authored-by:` trailer on commits\n"
            "# (you stay the author) and in GitHub/Jira footers.\n"
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
