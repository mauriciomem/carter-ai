"""File hashing, backup, and (templated) file installation primitives."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from carter.home import tilde
from carter.identity import ConfigError, load_identity, resolve
from carter.identity.trailer import noreply_email
from carter.install.console import log_debug, log_ok, log_skip
from carter.install.ownership import sha256_bytes


def _sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _backup_file(path: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    rel = path.name
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    log_debug(f"Backed up {path} → {dest}")


def _get_template_vars(config_path: Path) -> dict[str, str]:
    """Skill placeholders from the schema-2 identity (removed in step 15).

    No signing key is ever substituted, and no email is invented: at T0 (or with a
    legacy or broken config) the name is ``Carter`` and the email empty.
    """
    name, email = "Carter", ""
    try:
        cfg = load_identity(config_path)
        if resolve(cfg, workspace=None, env={}).tier != "t0":
            name, email = cfg.identity.login, noreply_email(cfg)
    except ConfigError:
        pass
    return {"{{BOT_NAME}}": name, "{{BOT_EMAIL}}": email, "{{SIGNING_KEY}}": ""}


def _install_content(
    dst: Path,
    content_hash: str,
    write: Callable[[], object],
    manifest: dict,
    backup_root: Path,
) -> str:
    """Install ``dst`` via ``write`` unless it already has ``content_hash``.

    A differing existing file is backed up first. ``dst`` is always recorded in
    the manifest with ``content_hash``. Returns ``created``, ``updated`` or
    ``unchanged``.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if _sha256(dst) == content_hash:
            log_skip(tilde(dst))
            status = "unchanged"
        else:
            _backup_file(dst, backup_root)
            write()
            log_ok(tilde(dst), "updated")
            status = "updated"
    else:
        write()
        log_ok(tilde(dst))
        status = "created"
    manifest["files"].append(str(dst))
    manifest["file_hashes"][str(dst)] = content_hash
    return status


def _install_templated_file(
    src: Path,
    dst: Path,
    manifest: dict,
    backup_root: Path,
    template_vars: dict[str, str],
) -> str:
    """Copy src to dst with template variable substitution. Returns status."""
    content = src.read_text()
    for placeholder, value in template_vars.items():
        content = content.replace(placeholder, value)
    return _install_rendered_file(content, dst, manifest, backup_root)


def _install_rendered_file(
    content: str,
    dst: Path,
    manifest: dict,
    backup_root: Path,
) -> str:
    """Write already-rendered ``content`` to ``dst`` (no source file to copy).

    Used to install rendered output, e.g. agents rendered from ``templates/``
    with OpenCode V2 ``permissions:`` frontmatter. Same backup/manifest/hash
    semantics as ``_install_file``.
    """
    return _install_content(
        dst,
        sha256_bytes(content.encode()),
        lambda: dst.write_text(content),
        manifest,
        backup_root,
    )


def _install_file(
    src: Path,
    dst: Path,
    manifest: dict,
    backup_root: Path,
) -> str:
    """Copy src to dst. Returns status: 'created', 'updated', or 'unchanged'."""
    return _install_content(
        dst, _sha256(src), lambda: shutil.copy2(src, dst), manifest, backup_root
    )
