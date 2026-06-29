"""File hashing, backup, and (templated) file installation primitives."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from carter.install.console import log_debug, log_ok, log_skip
from carter.install.paths import _home


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def _backup_file(path: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    rel = path.name
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    log_debug(f"Backed up {path} → {dest}")


def _get_template_vars(config_path: Path, bot_name: str) -> dict[str, str]:
    """Get template variables from config.toml or defaults."""
    bot_email = f"{bot_name}@users.noreply.github.com"
    signing_key = ""

    if config_path.exists():
        try:
            text = config_path.read_text()
            import re as _re

            # Parse bot name
            m = _re.search(r'^name\s*=\s*"(.+)"', text, _re.MULTILINE)
            if m:
                bot_name = m.group(1)
            # Parse bot email
            m = _re.search(r'^email\s*=\s*"(.+)"', text, _re.MULTILINE)
            if m:
                bot_email = m.group(1)
            # Parse signing key
            m = _re.search(r'^signing_key\s*=\s*"(.+)"', text, _re.MULTILINE)
            if m:
                signing_key = m.group(1)
        except Exception:
            pass

    # Fallback: auto-detect signing key
    if not signing_key:
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

    return {
        "{{BOT_NAME}}": bot_name,
        "{{BOT_EMAIL}}": bot_email,
        "{{SIGNING_KEY}}": signing_key,
    }


def _install_templated_file(
    src: Path,
    dst: Path,
    manifest: dict,
    backup_root: Path,
    template_vars: dict[str, str],
) -> str:
    """Copy src to dst with template variable substitution. Returns status."""
    dst.parent.mkdir(parents=True, exist_ok=True)

    content = src.read_text()
    for placeholder, value in template_vars.items():
        content = content.replace(placeholder, value)

    content_hash = hashlib.sha256(content.encode()).hexdigest()

    if dst.exists():
        dst_hash = _sha256(dst)
        if content_hash == dst_hash:
            log_skip(str(dst).replace(str(_home()), "~"))
            manifest["files"].append(str(dst))
            manifest["file_hashes"][str(dst)] = content_hash
            return "unchanged"
        _backup_file(dst, backup_root)
        dst.write_text(content)
        log_ok(f"{str(dst).replace(str(_home()), '~')}", "updated")
        manifest["files"].append(str(dst))
        manifest["file_hashes"][str(dst)] = content_hash
        return "updated"

    dst.write_text(content)
    log_ok(str(dst).replace(str(_home()), "~"))
    manifest["files"].append(str(dst))
    manifest["file_hashes"][str(dst)] = content_hash
    return "created"


def _install_rendered_file(
    content: str,
    dst: Path,
    manifest: dict,
    backup_root: Path,
) -> str:
    """Write already-rendered ``content`` to ``dst`` (no source file to copy).

    Used to install per-target-rendered output — e.g. OpenCode-shaped agent
    frontmatter, which differs from the copilot static ``agents/*.md`` (OpenCode
    rejects the copilot ``tools:`` array; it wants a ``permission`` block). Mirrors
    ``_install_file``'s backup/manifest/hash semantics; the hash carries the same
    ``sha256:`` prefix as ``_sha256`` so the unchanged-check matches on re-install.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    content_hash = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"

    if dst.exists():
        if _sha256(dst) == content_hash:
            log_skip(str(dst).replace(str(_home()), "~"))
            manifest["files"].append(str(dst))
            manifest["file_hashes"][str(dst)] = content_hash
            return "unchanged"
        _backup_file(dst, backup_root)
        dst.write_text(content)
        log_ok(f"{str(dst).replace(str(_home()), '~')}", "updated")
        manifest["files"].append(str(dst))
        manifest["file_hashes"][str(dst)] = content_hash
        return "updated"

    dst.write_text(content)
    log_ok(str(dst).replace(str(_home()), "~"))
    manifest["files"].append(str(dst))
    manifest["file_hashes"][str(dst)] = content_hash
    return "created"


def _install_file(
    src: Path,
    dst: Path,
    manifest: dict,
    backup_root: Path,
) -> str:
    """Copy src to dst. Returns status: 'created', 'updated', or 'unchanged'."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_hash = _sha256(src)

    if dst.exists():
        dst_hash = _sha256(dst)
        if src_hash == dst_hash:
            log_skip(str(dst).replace(str(_home()), "~"))
            manifest["files"].append(str(dst))
            manifest["file_hashes"][str(dst)] = src_hash
            return "unchanged"
        _backup_file(dst, backup_root)
        shutil.copy2(src, dst)
        log_ok(f"{str(dst).replace(str(_home()), '~')}", "updated")
        manifest["files"].append(str(dst))
        manifest["file_hashes"][str(dst)] = src_hash
        return "updated"

    shutil.copy2(src, dst)
    log_ok(str(dst).replace(str(_home()), "~"))
    manifest["files"].append(str(dst))
    manifest["file_hashes"][str(dst)] = src_hash
    return "created"
