"""The signing block: one pure function for the plugin and for ``carter commit`` (RFC-0007 §4.3).

``build_payload`` turns a resolved identity into the environment and git settings an LLM commit
needs to be signed by the LLM key, or says why it cannot (freeze H3). All or nothing: there is
never a partial block. ``to_git_env`` applies a block to an environment the way the plugin does.

Stdlib-only (the plugin calls ``python -I -m carter.identity.env`` per agent shell; it must stay
fast and must not import click or ``carter.guard``). It never opens a key and never talks to the
agent: a locked key still yields the block, and the commit then fails at signing with the raw git
error (``E-SIGN-LOCKED`` / ``E-SIGN-NOAGENT``).

Role ``author`` (2c, freeze K5) adds ``GIT_AUTHOR_NAME/EMAIL`` (the LLM) to the same dict: author,
committer, ``CARTER_IDENTITY`` and the signing entries are all present or all absent, so an
LLM-authored commit the human's key signs (hazard H7) cannot be produced. The human's identity is
only *checked* here (``human-identity-invalid``); the hook re-reads it at commit time.

Reasons (H3, K3), in the order they are decided: ``config-error``, ``tier-required``,
``key-missing``, ``fingerprint-mismatch``, ``shim-missing``, ``human-identity-invalid``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from carter.identity.coauthor import Human
from carter.identity.errors import E_CONFIG, E_ROLE_B_TIER
from carter.identity.isolation_apply import (
    Applied,
    append_git_config,
    drop_git_config_entries,
)
from carter.identity.pollution import count_state
from carter.identity.resolve import Resolution
from carter.identity.schema import TIERS, IdentityConfig
from carter.identity.trailer import noreply_email

SIGNING_KEYS = ("env", "git_config", "fingerprint")
SIGNING_ENV_KEYS = ("GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "CARTER_IDENTITY")
SIGNING_ENV_KEYS_B = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "CARTER_IDENTITY",
)
SIGNING_GIT_CONFIG_KEYS = ("gpg.format", "user.signingkey", "gpg.ssh.program", "commit.gpgsign")
REASONS = (
    "config-error",
    "tier-required",
    "key-missing",
    "fingerprint-mismatch",
    "shim-missing",
    "human-identity-invalid",
)

SHIM_REL = ".carter/bin/carter-ssh-sign"
GUARD_STATE_REL = ".carter/guard-state.json"
_KEY_TYPES = ("ssh-", "ecdsa-", "sk-")


def shim_path(home: Path | None = None) -> Path:
    """``~/.carter/bin/carter-ssh-sign`` (H2). ``home`` is the user's home directory."""
    return (home or Path.home()) / SHIM_REL


def public_blob(public_key: str) -> str:
    """``"type base64"`` from a public key line, comment dropped; ``""`` if it is not one.

    The key comment never leaves the config: it is dropped here once, for every consumer."""
    parts = public_key.split()
    if len(parts) < 2 or not parts[0].startswith(_KEY_TYPES):
        return ""
    try:
        base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError):
        return ""
    return f"{parts[0]} {parts[1]}"


def fingerprint_of(blob: str) -> str:
    """OpenSSH's ``SHA256:<base64 without padding>`` for a ``"type base64"`` blob."""
    digest = hashlib.sha256(base64.b64decode(blob.split()[1])).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


@dataclass(frozen=True)
class ShimState:
    """Is the shim there, executable and exactly what Carter wrote (guard-state hash)?"""

    path: str
    ok: bool


def shim_state(home: Path | None = None) -> ShimState:
    """Stat and hash the shim against ``files`` of ``guard-state.json``. No file is written.

    A missing file, a symlink, a non-executable file, a missing record or a different hash is
    ``ok=False`` (``shim-missing``): a shim the agent could have edited is no shim."""
    base = home or Path.home()
    path = shim_path(base)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not info.st_mode & stat.S_IXUSR:
            return ShimState(str(path), False)
        recorded = _recorded_hash(base / GUARD_STATE_REL, path)
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ShimState(str(path), False)
    return ShimState(str(path), recorded is not None and recorded == digest)


def _recorded_hash(state_file: Path, target: Path) -> str | None:
    try:
        files = json.loads(state_file.read_text(encoding="utf-8")).get("files", [])
        return next((f["sha256"] for f in files if f.get("path") == str(target)), None)
    except (OSError, ValueError, AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class Built:
    """``block`` and ``reason`` are never both set. Both ``None`` means "no signing here"
    (effective tier below T2): not an error, and nothing to apply."""

    block: dict[str, Any] | None = None
    reason: str | None = None


def build_payload(
    cfg: IdentityConfig,
    res: Resolution,
    shim: ShimState,
    human: Callable[[], Human] | None = None,
    *,
    role: str | None = None,
) -> Built:
    """The signing block for ``cfg`` at the resolved tier, or the reason there is none.

    ``human`` reads and validates the human's git identity; it is called only for role ``author``
    at T2 after every other check has passed (the role-a path stays free of git calls). ``role``
    overrides the resolved role (``carter commit`` passes ``co-author``: it ignores the role)."""
    if res.refusal_reason == E_CONFIG:
        return Built(reason="config-error")
    if res.refusal_reason == E_ROLE_B_TIER or _tier_unmet(res):
        return Built(reason="tier-required")
    if res.tier != "t2":
        return Built()
    blob = public_blob(cfg.signing.public_key)
    if not blob:
        return Built(reason="key-missing")
    if fingerprint_of(blob) != cfg.signing.fingerprint:
        return Built(reason="fingerprint-mismatch")
    if not shim.ok:
        return Built(reason="shim-missing")
    ident = cfg.identity
    llm = {"NAME": ident.name or ident.login, "EMAIL": noreply_email(cfg)}
    env: dict[str, str] = {}
    if (role or res.role) == "author":
        # Never degrades to co-author: no usable human identity, no block (K3, K4).
        if human is None or not human().ok:
            return Built(reason="human-identity-invalid")
        env = {"GIT_AUTHOR_NAME": llm["NAME"], "GIT_AUTHOR_EMAIL": llm["EMAIL"]}
    env |= {
        "GIT_COMMITTER_NAME": llm["NAME"],
        "GIT_COMMITTER_EMAIL": llm["EMAIL"],
        "CARTER_IDENTITY": ident.login,
    }
    return Built(
        block={
            "env": env,
            "git_config": [
                ["gpg.format", "ssh"],
                ["user.signingkey", f"key::{blob}"],
                ["gpg.ssh.program", shim.path],
                ["commit.gpgsign", "true"],
            ],
            "fingerprint": cfg.signing.fingerprint,
        }
    )


def _tier_unmet(res: Resolution) -> bool:
    return bool(res.require_tier) and TIERS.index(res.tier) < TIERS.index(res.require_tier)


def to_git_env(existing: Mapping[str, str], block: Mapping[str, Any]) -> Applied:
    """``existing`` with the signing block applied: committer env, then the git entries appended
    after any inherited ``GIT_CONFIG_COUNT`` entries (strict parse; a malformed count starts again
    at 0 and is flagged ``count-malformed``). ``GIT_CONFIG_PARAMETERS`` is deleted so a ``-c``
    smuggled through the environment cannot outrank the block. ``existing`` is not modified."""
    out = dict(existing)
    counted = count_state(existing)
    flags: list[str] = []
    if counted.state == "polluted":
        drop_git_config_entries(out)
        flags.append("count-malformed")
    out.pop("GIT_CONFIG_PARAMETERS", None)
    out.update(block["env"])
    append_git_config(out, counted.n, [list(pair) for pair in block["git_config"]])
    return Applied(out, flags)
