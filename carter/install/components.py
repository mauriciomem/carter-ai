"""Component installers: agents, skills, OpenCode rules, knowledge, memories, ops.

Plus the install manifest read/write. OpenCode is the only install target;
the knowledge base, manifest and backups live under ``~/.carter`` (see
``carter.install.paths``).
"""

from __future__ import annotations

import json
import shlex
import shutil
from datetime import UTC, datetime
from pathlib import Path

from carter.aplus.push import OWN_TERMINAL
from carter.home import tilde
from carter.identity import ConfigError
from carter.identity.config import read_document
from carter.identity.schema import IdentityConfig
from carter.identity.writer import dumps, write_config
from carter.install.backups import BackupRoot
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
    backups_dir,
    knowledge_dir,
    manifest_path,
)


def install_agents(
    base_dir: Path | None,
    manifest: dict,
    backup_root: BackupRoot,
) -> dict[str, int]:
    """Install the OpenCode agents rendered from the shipped guarded defaults."""
    log_step("Installing agents...")
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}
    for name, content in sorted(_render_opencode_agents(base_dir).items()):
        dst = _opencode_base(base_dir) / "agents" / name
        status = _install_rendered_file(content, dst, manifest, backup_root)
        stats[status] += 1
    return stats


def rerender_agents(base_dir: Path | None) -> dict[str, int] | None:
    """Re-write the global Carter agent files and their manifest entries.

    ``carter guard install`` and ``remove`` call this after the guard state changed: G2's deny
    set is part of each agent's ``permissions:``. Nothing happens without a manifest (no
    ``carter install`` ran here). Returns the per-file statuses, or ``None`` when skipped."""
    manifest = read_manifest(base_dir)
    if manifest is None:
        return None
    agents_dir = _opencode_base(base_dir) / "agents"
    ours = {str(agents_dir / name) for name in _render_opencode_agents(base_dir)}
    manifest["files"] = [f for f in manifest["files"] if f not in ours]
    stats = install_agents(base_dir, manifest, BackupRoot(backups_dir(base_dir)))
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    write_manifest(manifest, base_dir)
    return stats


def _render_opencode_agents(base_dir: Path | None = None) -> dict[str, str]:
    """Render the OpenCode-shaped agent files from the shipped guarded defaults.

    Returns ``{filename: content}`` keyed by ``carter-<role>.md`` (no agent suffix —
    global installs use canonical names), each carrying G2's rules as the guard state of
    ``base_dir`` records them. The scaffold/Jinja stack is imported lazily so importing
    the installer stays cheap.
    """
    from carter.config import generate_default_config
    from carter.guard.agent_rules import current_rules
    from carter.scaffold import create_env, render_agents

    cfg = generate_default_config(workspace_name="carter", mode="single")
    cfg["agent_suffix"] = ""
    # Global agents serve every workspace: defer to each workspace's docs_language.
    cfg["docs_language"] = None
    return render_agents(cfg, create_env(), current_rules(base_dir))


def install_skills(
    base_dir: Path | None,
    manifest: dict,
    backup_root: BackupRoot,
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


def remove_retired_skills(base_dir: Path | None, previous: dict | None) -> int:
    """Remove ``carter-*`` skills Carter no longer ships, if still Carter-owned.

    A retired skill directory is deleted only when every file in it is listed in
    the previous install manifest and still has its recorded hash. Otherwise it is
    kept and the user is told how to remove it. Non-``carter-*`` skills and skills
    Carter still ships are never touched. Nothing is copied first: what goes is Carter's own
    unchanged output. Returns the number of skills removed.
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
            # A name is the user's (or an agent's) input: quoted, absolute, and no command at all
            # for one with a control character in it.
            rm = f": rm -r {shlex.quote(str(skill))}" if str(skill).isprintable() else ""
            log_warn(
                f"{shown} (no longer shipped by Carter; edited or not recorded, kept)",
                hint=f"remove it manually if unused{rm}",
            )
            continue
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

# Global rules, Communication section. AGENTS.md loads in every session, so it stays short.
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

# The commit-attribution rule: installed into the global AGENTS.md.
_ATTRIBUTION_RULE = (
    "- Commits: the user is the author (their own git config) unless `carter ops config --emit`"
    " says `author` is `llm` (role author); the committer is the user, or"
    " the LLM when signing is on. Never pass `--author`, `--no-verify`, `-s` or `-S`, never set"
    " `GIT_AUTHOR_*` or `GIT_COMMITTER_*`, and never add `Signed-off-by` unless the user asks."
    " Credit comes only"
    " from the `coauthor_trailer` it prints; if `commits` is `refused`, stop and report.\n"
    "- Pushing is human-only: tell the user: "
    + OWN_TERMINAL
    + " Only carter-devops may ask with `carter_push`; the user approves each use."
    " After the push, `gh pr create` is fine.\n"
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


def install_opencode_rules(
    base_dir: Path | None, manifest: dict, previous: dict | None = None
) -> None:
    """Generate ~/.config/opencode/AGENTS.md for OpenCode global rules.

    A missing file is written; the current text is kept. A file whose hash is the one the
    previous install recorded was never edited by the user, so it is upgraded in place.
    Anything else is the user's ("user-modified"): it is never touched.
    """
    log_step("Installing OpenCode global rules...")
    dst = _opencode_base(base_dir) / "AGENTS.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shown = tilde(dst)
    owned = True
    recorded = ((previous or {}).get("file_hashes") or {}).get(str(dst))
    if not dst.exists():
        dst.write_text(_OPENCODE_AGENTS_MD, encoding="utf-8")
        log_ok(shown)
    elif dst.read_text(encoding="utf-8") == _OPENCODE_AGENTS_MD:
        log_skip(f"{shown} (already current)")
    elif recorded and _hash_matches(dst, str(recorded)):
        dst.write_text(_OPENCODE_AGENTS_MD, encoding="utf-8")
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
    backup_root: BackupRoot,
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


def default_config_text() -> str:
    """The exact text ``install`` writes to a missing ``config.toml``."""
    return dumps(IdentityConfig(state="current"))


def ensure_config(path: Path) -> bool:
    """Write the schema-2 defaults if there is no file. Returns True if it wrote. An existing file
    is never touched (``ConfigError`` if it does not parse)."""
    if read_document(path) is not None:
        return False
    write_config(IdentityConfig(state="current"), path)
    return True


def install_ops(base_dir: Path | None, manifest: dict) -> bool:
    """Create ``~/.carter/config.toml`` (schema 2) if it is missing. Returns True if created.

    A missing file gets the defaults (T0: no identity, no signing key). An existing file is
    never touched; a file that does not parse is reported and left alone, and the rest of the
    install goes on (identity stays fail-closed).
    """
    log_step("Configuring carter-ops...")
    config_path = _carter_base(base_dir) / "config.toml"
    try:
        created = ensure_config(config_path)
    except ConfigError as exc:
        log_err(f"{tilde(config_path)} not read: {exc} ({exc.detail})")
        return False
    if not created:
        log_skip(f"{tilde(config_path)} (not touched)")
        return False
    log_ok(tilde(config_path), "created")
    manifest["files"].append(str(config_path))
    return True


def write_manifest(manifest: dict, base_dir: Path | None) -> Path:
    path = manifest_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Hashes are kept only for the paths the manifest still lists.
    listed = set(manifest.get("files", []))
    hashes = {k: v for k, v in manifest.get("file_hashes", {}).items() if k in listed}
    text = json.dumps({**manifest, "file_hashes": hashes}, indent=2)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read_manifest(base_dir: Path | None) -> dict | None:
    """Read ``~/.carter/manifest.json``, or ``None`` if absent."""
    path = manifest_path(base_dir)
    if path.exists():
        data: dict = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("files", [])
        data.setdefault("file_hashes", {})
        data.setdefault("mcp_servers", [])
        return data
    return None
