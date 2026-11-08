"""Component installers: agents, skills, OpenCode rules, knowledge, memories, ops.

Plus the install manifest read/write. OpenCode is the only install target;
the knowledge base, manifest and backups live under ``~/.carter`` (see
``carter.install.paths``).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from carter import __version__
from carter.aplus.handoff import OWN_TERMINAL
from carter.home import tilde
from carter.identity import ConfigError
from carter.identity.migrate import MigrationError, ensure_config
from carter.install.console import log_err, log_ok, log_skip, log_step, log_warn
from carter.install.files import (
    _install_file,
    _install_rendered_file,
    _sha256,
)
from carter.install.ownership import _hash_matches
from carter.install.paths import (
    REPO_ROOT,
    _carter_base,
    _opencode_base,
    knowledge_dir,
    manifest_path,
)


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
    global installs use canonical names). The scaffold/Jinja stack is imported
    lazily so importing the installer stays cheap.
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
) -> dict[str, int]:
    log_step("Installing skills...")
    src_dir = REPO_ROOT / "skills"
    # Per-file statuses, plus "skills": the number of skill directories installed.
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0, "skills": 0}

    for skill_dir in sorted(src_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        stats["skills"] += 1

        skill_files = [f for f in sorted(skill_dir.iterdir()) if f.is_file()]
        for src_file in skill_files:
            rel = src_file.relative_to(skill_dir)

            dst = _opencode_base(base_dir) / "skills" / skill_dir.name / rel
            stats[_install_file(src_file, dst, manifest, backup_root)] += 1

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
        shown = tilde(skill)
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

# Global rules §Communication (only this section: AGENTS.md loads every session,
# so its token cost must stay small). Written as implicit concatenation purely to satisfy
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

# The commit-attribution rule. One constant: it is installed into the global AGENTS.md and
# is also the text of the upgrade note for users whose AGENTS.md we must not rewrite.
_ATTRIBUTION_RULE = (
    "- Commits: the user is the author (their own git config) unless `carter ops config --emit`"
    " says `author` is `llm` (role b); the committer is the user, or"
    " the LLM at T2. Never pass `--author`, `--no-verify`, `-s` or `-S`, never set `GIT_AUTHOR_*`"
    " or `GIT_COMMITTER_*`, and never add `Signed-off-by` unless the user asks. Credit comes only"
    " from the `coauthor_trailer` it prints; if `commits` is `refused`, stop and report.\n"
    "- Pushing and every other GitHub write are human-only. When a branch is ready, write"
    " the handoff file (`carter-ops` skill) and tell the user: " + OWN_TERMINAL + "\n"
)

# The "Git & Language" global rules (also rendered into the workspace AGENTS.md).
_OPENCODE_GIT_LANGUAGE = (
    "\n## Git & Language\n"
    + _ATTRIBUTION_RULE
    + "- Everything that lands in a repository or leaves the workspace is written in"
    " English, whatever language the conversation uses: commit messages, branch names,"
    " code comments, repo docs, PR/issue titles and bodies, review comments, release"
    " notes, Jira and Slack text.\n"
    "- Carter's internal docs (ADRs, RFCs, `.carter/` plans/knowledge/checkpoints,"
    " memories) use the workspace `docs_language` from `.carter/carter.yaml`; without"
    " one, English unless the user asks for another language.\n"
    "- Talk to the user in their own language.\n"
)

_OPENCODE_AGENTS_MD = _OPENCODE_AGENTS_MD_BASE + _OPENCODE_COMMUNICATION + _OPENCODE_GIT_LANGUAGE

# sha256 of each global AGENTS.md text Carter shipped before this one: up to v0.16.x, v0.17.x
# (commit rule only, without the handoff rule) and v0.18.0 (before signing). A file with exactly
# one of these was never edited by the user, so it is upgraded in place.
_KNOWN_PREVIOUS_AGENTS_MD_SHA256 = frozenset(
    {
        "f96032e740c9fc9660d0798c36ed38b53aa12d7323b21bddf338834ca37d5401",
        "252415df75dd375f9afe2189572c14b90930f35e14f2ac14eeb26752f1e86eeb",
        "7aea1b84a6693292380e2c15796dcd33b612e8c2787af40e90b1b3c83f31e0a1",  # v0.18.0 (plan 005)
        "15a896f96a1c6e172e66e51c54a1553cac04c8ba0bef913c0cd8072a8144a6c6",  # the 2b text
        "cb82e2be4bc215ef7f517663b49be7f774d492c9f19bfd358f14d5ec6153f1ae",  # before D68 g
    }
)


def _upgrade_note_text() -> str:
    return (
        f"# Carter {__version__}: commit attribution rule\n\n"
        "Your global rules file (`~/.config/opencode/AGENTS.md`) has your own edits, so Carter\n"
        "left it alone. Replace the commit/author/signing line in its Git & Language section\n"
        "with these two rules (commits, and pushing as a human-only step):\n\n" + _ATTRIBUTION_RULE
    )


def _write_upgrade_note(base_dir: Path | None, shown_agents_md: str) -> None:
    """Print the new rule and save it to ``~/.carter/upgrade-notes/<version>.md`` once.

    The file is written atomically (tmp + replace, mode 0644) and a failure never blocks
    the install. It is not in the manifest: it is the user's reminder, not Carter's state."""
    note = _carter_base(base_dir) / "upgrade-notes" / f"{__version__}.md"
    if note.exists():
        log_warn(f"{shown_agents_md}: attribution rule still to merge, see {tilde(note)}")
        return
    text = _upgrade_note_text()
    log_warn(f"{shown_agents_md}: not updated. Merge this rule by hand:")
    print(text)
    try:
        note.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=note.parent, prefix=".note.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(tmp, 0o644)
            os.replace(tmp, note)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        log_ok(tilde(note), "saved")
    except OSError as exc:
        log_warn(f"could not save the upgrade note ({type(exc).__name__})")


def install_opencode_rules(
    base_dir: Path | None, manifest: dict, previous: dict | None = None
) -> None:
    """Generate ~/.config/opencode/AGENTS.md for OpenCode global rules.

    A missing file is written; the current text is kept. A file that is exactly a text
    Carter shipped before (known hash, or the hash the previous install recorded) is
    upgraded in place. Anything else is the user's: it is never touched, and the new
    attribution rule is printed and saved as an upgrade note instead.
    """
    log_step("Installing OpenCode global rules...")
    dst = _opencode_base(base_dir) / "AGENTS.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shown = tilde(dst)
    owned = True
    recorded = ((previous or {}).get("file_hashes") or {}).get(str(dst))
    if not dst.exists():
        dst.write_text(_OPENCODE_AGENTS_MD)
        log_ok(shown)
    elif dst.read_text() == _OPENCODE_AGENTS_MD:
        log_skip(f"{shown} (already current)")
    elif _sha256(dst).removeprefix("sha256:") in _KNOWN_PREVIOUS_AGENTS_MD_SHA256 or (
        recorded and _hash_matches(dst, str(recorded))
    ):
        dst.write_text(_OPENCODE_AGENTS_MD)
        log_ok(shown, "updated (was an unmodified earlier Carter version)")
    else:
        # User-modified — NEVER clobber.
        log_warn(
            f"{shown} (user-modified, skipping)",
            hint="merge the Communication and Git & Language sections manually",
        )
        manifest.setdefault("notes", []).append(
            f"{shown}: user-modified, current Carter rules not installed"
        )
        _write_upgrade_note(base_dir, shown)
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
            log_skip(f"{tilde(scope_dir)} (exists)")
        else:
            scope_dir.mkdir(parents=True, exist_ok=True)
            log_ok(tilde(scope_dir))
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
            log_skip(f"{tilde(dst)} (exists, not overwriting)")
            # Knowledge is user data: an existing file is Carter-owned only if it
            # is byte-identical to the seed. Anything else (user-written, edited,
            # restored from a backup) is never recorded, so uninstall keeps it.
            seed_hash = _sha256(src_file)
            if _sha256(dst) == seed_hash:
                manifest["files"].append(str(dst))
                manifest["file_hashes"][str(dst)] = seed_hash
        else:
            _install_file(src_file, dst, manifest, backup_root)
            count += 1

    return count


def install_ops(base_dir: Path | None, manifest: dict) -> bool:
    """Create or migrate ``~/.carter/config.toml`` (schema 2). Returns True if it changed.

    A missing file gets schema-2 defaults (T0: no identity, no signing key). A schema-1
    file is migrated once, after a ``config.toml.schema1.bak`` backup that is never
    overwritten and never listed in the manifest (uninstall must not delete it). A schema-2
    file is left alone. A file that cannot be migrated is reported and left untouched; the
    rest of the install goes on and identity stays fail-closed.
    """
    log_step("Configuring carter-ops...")
    config_path = _carter_base(base_dir) / "config.toml"
    try:
        result = ensure_config(config_path)
    except (ConfigError, MigrationError) as exc:
        detail = getattr(exc, "detail", "")
        log_err(f"{tilde(config_path)} not migrated: {exc}{f' ({detail})' if detail else ''}")
        return False
    for warning in result.warnings:
        log_warn(warning)
    if result.status == "current":
        log_skip(f"{tilde(config_path)} (schema 2, not touched)")
        return False
    log_ok(tilde(config_path), "created" if result.status == "created" else "migrated to schema 2")
    if result.backup:
        log_ok(tilde(result.backup), "backup of the schema-1 file")
    manifest["files"].append(str(config_path))
    return True


def write_manifest(manifest: dict, base_dir: Path | None) -> Path:
    path = manifest_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def read_manifest(base_dir: Path | None) -> dict | None:
    """Read ``~/.carter/manifest.json``, or ``None`` if absent."""
    path = manifest_path(base_dir)
    if path.exists():
        data: dict = json.loads(path.read_text())
        data.setdefault("files", [])
        data.setdefault("file_hashes", {})
        data.setdefault("mcp_servers", [])
        return data
    return None
