"""Component installers: agents, skills, OpenCode rules, knowledge, memories, ops.

Plus the install manifest read/write. OpenCode is the only install target
(ADR-0014); the knowledge base, manifest and backups live under ``~/.carter``
(D3, see ``carter.install.paths``).
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
from carter.install.ownership import _hash_matches
from carter.install.paths import (
    REPO_ROOT,
    _carter_base,
    _home,
    _opencode_base,
    knowledge_dir,
    manifest_path,
)
from carter.install.rules_history import SHIPPED_GLOBAL_RULES


def install_agents(
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> dict[str, int]:
    """Install the OpenCode agents rendered from the shipped guarded defaults."""
    log_step("Installing agents...")
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}
    for name, content in sorted(_render_opencode_agents().items()):
        dst = _opencode_base(base_dir) / "agents" / name
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
    cfg["agent_suffix"] = ""
    # Global agents serve every workspace: defer to each workspace's docs_language.
    cfg["docs_language"] = None
    return render_agents(cfg, create_env())


def install_skills(
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

            dst = _opencode_base(base_dir) / "skills" / skill_dir.name / rel
            if needs_template:
                status = _install_templated_file(
                    src_file, dst, manifest, backup_root, template_vars
                )
            else:
                status = _install_file(src_file, dst, manifest, backup_root)
            stats[status] += 1

    return stats


def remove_retired_skills(
    base_dir: Path | None,
    previous: dict | None,
    backup_root: Path,
) -> int:
    """Remove ``carter-*`` skills Carter no longer ships, if still Carter-owned.

    A retired skill directory is deleted only when every file in it is listed in
    the previous install manifest and still has its recorded hash. Otherwise it is
    kept and the user is told how to remove it. Non-``carter-*`` skills and skills
    Carter still ships are never touched. Returns the number of skills removed.
    """
    skills_root = _opencode_base(base_dir) / "skills"
    if not skills_root.is_dir():
        return 0
    shipped = {d.name for d in (REPO_ROOT / "skills").iterdir() if (d / "SKILL.md").is_file()}
    hashes: dict = (previous or {}).get("file_hashes") or {}
    removed = 0
    for skill in sorted(skills_root.iterdir()):
        if not skill.name.startswith("carter-") or skill.name in shipped:
            continue
        shown = str(skill).replace(str(_home()), "~")
        if skill.is_symlink() or not skill.is_dir():
            owned = False
        else:
            files = [f for f in skill.rglob("*") if not f.is_dir()]
            owned = bool(files) and all(
                not f.is_symlink() and str(f) in hashes and _hash_matches(f, str(hashes[str(f)]))
                for f in files
            )
        if not owned:
            log_warn(
                f"{shown} (no longer shipped by Carter; edited or not recorded, kept)",
                hint=f"remove it manually if unused: rm -r {shown}",
            )
            continue
        shutil.copytree(skill, backup_root / "retired-skills" / skill.name, dirs_exist_ok=True)
        shutil.rmtree(skill)
        log_ok(f"{shown} (removed: no longer shipped by Carter)")
        removed += 1
    return removed


_OPENCODE_AGENTS_MD_BASE = """\
# Carter — Global Rules

When the user's request starts with `ops:`, load the `carter-ops` skill and follow
its instructions exactly.

## Memory
- Record mistakes and key learnings to `~/.carter/memories/`.
- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for
  project-specific notes, and `session/` for conversation-scoped working notes.
- Consult `~/.carter/memories/` and `~/.carter/knowledge/` before proposing
  solutions to check for past decisions and lessons.
"""

# Global rules §Communication (D2: only this section — AGENTS.md loads every session,
# so token cost is disciplined). Written as implicit concatenation purely to satisfy
# the line-length lint.
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

# The "Git & Language" global rules (also rendered into the workspace AGENTS.md).
_OPENCODE_GIT_LANGUAGE = (
    "\n## Git & Language\n"
    "- You (the user) are always the commit author and sign with your own key. Never"
    " pass `--author`; credit Carter only with a trailer:"
    " `Co-authored-by: <name> <email>` from `[attribution]` in"
    " `~/.carter/config.toml` (default `carter-bot <carter-bot@users.noreply.github.com>`).\n"
    "- Everything that lands in a repository or leaves the workspace is written in"
    " English, whatever language the conversation uses: commit messages, branch names,"
    " code comments, repo docs, PR/issue titles and bodies, review comments, release"
    " notes, Jira and Slack text.\n"
    "- Carter's internal docs (ADRs, RFCs, `.carter/` plans/knowledge/checkpoints,"
    " memories) use the workspace `docs_language` from `.carter/carter.yaml`; without"
    " one, English unless the user asks for another language.\n"
    "- Talk to the user in their own language.\n"
)

_OPENCODE_AGENTS_MD = _OPENCODE_AGENTS_MD_BASE + _OPENCODE_COMMUNICATION + _OPENCODE_GIT_LANGUAGE

# Unmodified earlier versions that install_opencode_rules may upgrade in place.
# When the text above changes, append the outgoing version to rules_history.
_OPENCODE_AGENTS_MD_KNOWN = SHIPPED_GLOBAL_RULES


def install_opencode_rules(
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> None:
    """Generate ~/.config/opencode/AGENTS.md for OpenCode global rules."""
    log_step("Installing OpenCode global rules...")
    dst = _opencode_base(base_dir) / "AGENTS.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shown = str(dst).replace(str(_home()), "~")
    owned = True
    if not dst.exists():
        dst.write_text(_OPENCODE_AGENTS_MD)
        log_ok(shown)
    elif dst.read_text() in _OPENCODE_AGENTS_MD_KNOWN:
        # Unmodified earlier content (hash-idempotency philosophy): safe to upgrade.
        dst.write_text(_OPENCODE_AGENTS_MD)
        log_ok(f"{shown} (upgraded to the current Carter rules)")
    elif dst.read_text() == _OPENCODE_AGENTS_MD:
        log_skip(f"{shown} (already current)")
    else:
        # User-modified — NEVER clobber.
        log_warn(
            f"{shown} (user-modified, skipping)",
            hint="merge the Communication and Git & Language sections manually",
        )
        manifest.setdefault("notes", []).append(
            f"{shown}: user-modified, current Carter rules not installed"
        )
        owned = False
    if owned:
        # Recorded with its hash so uninstall can tell if the user edits it later.
        manifest["files"].append(str(dst))
        manifest["file_hashes"][str(dst)] = _sha256(dst)


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
    dst_dir = knowledge_dir(base_dir)
    count = 0

    for src_file in sorted(src_dir.glob("*.md")):
        dst = dst_dir / src_file.name
        if dst.exists():
            log_skip(f"{str(dst).replace(str(_home()), '~')} (exists, not overwriting)")
            # Knowledge is user data: an existing file is Carter-owned only if it
            # is byte-identical to the seed. Anything else (user-written, edited,
            # migrated from ~/.copilot) is never recorded, so uninstall keeps it.
            seed_hash = _sha256(src_file)
            if _sha256(dst) == seed_hash:
                manifest["files"].append(str(dst))
                manifest["file_hashes"][str(dst)] = seed_hash
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
    path = manifest_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def normalize_manifest(data: dict) -> dict:
    """Accept both manifest shapes.

    Pre-ADR-0014 manifests kept ``mcp_servers`` as ``{target: [names]}``; the
    current shape is a flat list. Old dicts are flattened (de-duplicated, order
    kept) so callers only ever see the list form.
    """
    servers = data.get("mcp_servers")
    if isinstance(servers, dict):
        flat: list[str] = []
        for names in servers.values():
            for name in names or []:
                if name not in flat:
                    flat.append(name)
        data["mcp_servers"] = flat
    elif servers is None:
        data["mcp_servers"] = []
    data.setdefault("files", [])
    data.setdefault("file_hashes", {})
    return data


def read_manifest(base_dir: Path | None) -> dict | None:
    """Read ``~/.carter/manifest.json`` (either shape), or ``None`` if absent."""
    path = manifest_path(base_dir)
    if path.exists():
        return normalize_manifest(json.loads(path.read_text()))
    return None
