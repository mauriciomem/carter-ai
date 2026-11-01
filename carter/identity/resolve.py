"""Pure tier and role resolution (RFC-0007 §4.1). No I/O, no environment reads.

The caller passes the parsed config, the workspace path and the environment mapping, so
the same inputs always give the same answer and nothing here can write or run git.
Slice 1 only *reports* the result; wiring it to commits is slice 2b.

``carter.yaml`` is deliberately not an input: its ``identity.role`` and
``identity.require_tier`` reach this module only after a human runs ``carter update``
and pins them under ``[workspaces."<path>"]`` (D62).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from carter.identity.errors import (
    E_CONFIG,
    E_ROLE_B_TIER,
    MSG_CONFIG,
    MSG_ROLE_B_TIER,
    IdentityError,
)
from carter.identity.schema import ROLES, TIERS, IdentityConfig, Workspace

ENV_ROLE = "CARTER_IDENTITY_ROLE"
NOREPLY_DOMAIN = "users.noreply.github.com"
_NOREPLY = re.compile(rf"(\d+)\+([A-Za-z0-9][A-Za-z0-9_-]*)@{re.escape(NOREPLY_DOMAIN)}")

RoleSource = Literal["workspace", "env", "config", "default"]


def is_noreply_email(email: str, *, login: str | None = None, uid: int | None = None) -> bool:
    """True for ``<id>+<login>@users.noreply.github.com``.

    The old ``carter-bot@users.noreply.github.com`` default has no id and is rejected.
    With ``login``/``uid`` the address must also match them (logins compare
    case-insensitively, as GitHub treats them).
    """
    m = _NOREPLY.fullmatch(email)
    if not m:
        return False
    if login is not None and m.group(2).lower() != login.lower():
        return False
    return uid is None or int(m.group(1)) == uid


def _identity_touched(cfg: IdentityConfig) -> bool:
    ident = cfg.identity
    return bool(ident.login or ident.id or ident.email)


def _has_identity(cfg: IdentityConfig) -> bool:
    ident = cfg.identity
    if not ident.login or ident.id <= 0:
        return False
    return not ident.email or is_noreply_email(ident.email, login=ident.login, uid=ident.id)


# Any of these means the user set up signing; ttl/ssh_bin_dir/format have defaults.
_SIGNING_MATERIAL = (
    "public_key",
    "public_key_path",
    "fingerprint",
    "private_key_path",
    "agent_socket",
    "program",
)


def _has_signing_material(cfg: IdentityConfig) -> bool:
    return any(getattr(cfg.signing, name) for name in _SIGNING_MATERIAL)


def _has_signing_key(cfg: IdentityConfig) -> bool:
    """The public half as a blob plus its fingerprint; a path alone is not enough (the
    pure reader cannot open it, and the shim works on the blob)."""
    s = cfg.signing
    return s.format == "ssh" and bool(s.fingerprint) and bool(s.public_key)


def _missing_for_t2(cfg: IdentityConfig) -> tuple[str, ...]:
    """Key names (never values) that keep a signing setup from being T2."""
    missing = [] if _has_identity(cfg) else ["identity.login", "identity.id", "identity.email"]
    if not cfg.signing.public_key:
        missing.append("identity.signing.public_key")
    if not cfg.signing.fingerprint:
        missing.append("identity.signing.fingerprint")
    return tuple(missing)


def configured_tier(cfg: IdentityConfig) -> str:
    """T0 nothing usable, T1 a consistent login/id/noreply identity, T2 plus a signing key.

    A broken signing setup is not T1: ``resolve`` refuses it (E-CONFIG). A schema-1 file
    (``needs_migration``) carries no identity, so it is T0.
    """
    if cfg.needs_migration or not _has_identity(cfg):
        return "t0"
    if _has_signing_material(cfg):
        return "t2" if _has_signing_key(cfg) else "t0"
    return "t1"


def effective_tier(configured: str, cap: str) -> str:
    """``min(configured, cap)`` (D64). An empty cap means none; an unknown cap fails safe
    to T0. A cap never raises the tier."""
    if not cap:
        return configured
    if cap not in TIERS:
        return "t0"
    return min(configured, cap, key=TIERS.index)


@dataclass(frozen=True)
class RoleResolution:
    role: str
    source: RoleSource
    warnings: tuple[str, ...] = ()


def resolve_role(
    cfg: IdentityConfig, workspace: str | None, env: Mapping[str, str]
) -> RoleResolution:
    """Pinned workspace role > ``CARTER_IDENTITY_ROLE`` > ``[identity] role`` > co-author."""
    pinned = _workspace(cfg, workspace).role
    if pinned:
        return RoleResolution(pinned, "workspace")
    warnings: tuple[str, ...] = ()
    session = env.get(ENV_ROLE, "")
    if session in ROLES:
        return RoleResolution(session, "env")
    if session:  # a typo must not silently pick another role; never echo the value
        warnings = (f"{ENV_ROLE} is not one of {list(ROLES)}; ignored",)
    if cfg.identity.role != "co-author":
        return RoleResolution(cfg.identity.role, "config", warnings)
    return RoleResolution("co-author", "default", warnings)


def _workspace(cfg: IdentityConfig, path: str | None) -> Workspace:
    return cfg.workspaces.get(path, Workspace()) if path is not None else Workspace()


@dataclass(frozen=True)
class Resolution:
    """The answer for one workspace. Field names feed ``carter ops config --emit``."""

    configured_tier: str
    cap: str
    tier: str  # effective: min(configured, cap)
    role: str
    role_source: RoleSource
    commits: Literal["allowed", "refused"]
    refusal_reason: str  # an error code, "" when allowed
    require_tier: str  # pinned minimum; enforced by the plugin and `carter commit` (2a/2b)
    migration_needed: bool
    warnings: tuple[str, ...] = ()
    refusal_detail: str = ""  # key names only, never values

    def ensure_commits_allowed(self) -> None:
        """Raise ``IdentityError`` carrying the refusal code if commits are refused."""
        if self.refusal_reason == E_ROLE_B_TIER:
            raise IdentityError(E_ROLE_B_TIER, MSG_ROLE_B_TIER)
        if self.refusal_reason == E_CONFIG:
            raise IdentityError(E_CONFIG, MSG_CONFIG, self.refusal_detail)


def resolve(cfg: IdentityConfig, *, workspace: str | None, env: Mapping[str, str]) -> Resolution:
    """Resolve tier and role.

    Refusals, in order: a signing setup that is not a complete T2 (E-CONFIG, no fallback
    to T1/T0, RFC §4.1), then role ``author`` below T2 (E-ROLE-B-TIER, never downgraded).
    """
    ws = _workspace(cfg, workspace)
    configured = configured_tier(cfg)
    tier = effective_tier(configured, ws.max_tier)
    role = resolve_role(cfg, workspace, env)
    warnings = list(role.warnings)
    reason, detail = "", ""
    missing = _missing_for_t2(cfg)
    if not cfg.needs_migration and _has_signing_material(cfg) and missing:
        reason = E_CONFIG
        detail = "signing is configured but incomplete; missing or inconsistent: " + ", ".join(
            missing
        )
        warnings.append(detail)
    elif role.role == "author" and tier != "t2":
        reason = E_ROLE_B_TIER
    if reason != E_CONFIG and configured == "t0" and _identity_touched(cfg):
        warnings.append("identity is incomplete or inconsistent (login, id, email); treated as T0")
    return Resolution(
        configured_tier=configured,
        cap=ws.max_tier,
        tier=tier,
        role=role.role,
        role_source=role.source,
        commits="refused" if reason else "allowed",
        refusal_reason=reason,
        require_tier=ws.require_tier,
        migration_needed=cfg.needs_migration,
        warnings=tuple(warnings),
        refusal_detail=detail,
    )
