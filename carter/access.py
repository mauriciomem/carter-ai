"""Access levels: the capability schema and the resolver.

Pure functions: no files, no environment, no printing. The caller passes what it read
(``[access]`` of ``~/.carter/config.toml``, ``access:`` and ``policy.level`` of
``.carter/carter.yaml``, the role) and gets back one value per capability, where each
value came from, and the user-visible lines (every one <= 80 chars). Printing the lines,
once, is the caller's job.

``CAPABILITY_IDS`` and ``FLOOR_IDS`` are the single source of the ids: the loader, the
renderer and ``carter access`` all take them from here.

Merge: each side is expanded to one value per id, then the strictest per
id of user, workspace and role wins (``allowed < ask < denied``). Any error in the user's
``[access]`` fails closed to ``strict``. A workspace can only harden.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

VALUES = ("allowed", "ask", "denied")  # loosest first
RANK = {value: rank for rank, value in enumerate(VALUES)}
LEVELS = ("strict", "guarded", "relaxed")  # strictest first
NEVER = "never"  # what the floor shows; never a configurable value


@dataclass(frozen=True)
class Capability:
    """One adjustable row. ``max`` is the loosest value an override may set."""

    id: str
    label: str
    presets: tuple[str, str, str]  # in LEVELS order: strict, guarded, relaxed
    max: str

    def preset(self, level: str) -> str:
        return self.presets[LEVELS.index(level)]


CAPABILITIES: tuple[Capability, ...] = (
    Capability("workspace_edit", "Workspace edits", ("allowed", "allowed", "allowed"), "allowed"),
    Capability("run_commands", "Run commands", ("allowed", "allowed", "allowed"), "allowed"),
    Capability("git_commit", "Git commit", ("allowed", "allowed", "allowed"), "allowed"),
    Capability("github_read", "GitHub reads", ("allowed", "allowed", "allowed"), "allowed"),
    Capability("pr_write", "PR writes", ("ask", "allowed", "allowed"), "allowed"),
    Capability("issue_write", "Issue writes", ("denied", "ask", "allowed"), "allowed"),
    Capability("destructive", "Destructive", ("denied", "ask", "ask"), "ask"),
    Capability("infra_apply", "Infra apply", ("denied", "ask", "ask"), "ask"),
    Capability("opencode_config", "OpenCode config", ("denied",) * 3, "denied"),
)

# The floor: shown as `never`; no level, override or workspace opens them.
# Labels stay <= 16 chars so a plain row fits 60 columns (see `carter.access_cli`).
FLOOR: tuple[tuple[str, str], ...] = (
    ("push", "Push from shell"),
    ("gh_api", "GitHub API"),
    ("github_admin", "GitHub decisions"),
    ("sudo", "Root"),
    ("secrets", "Secrets"),
    ("carter_internals", "Carter internals"),
)

CAPABILITY_IDS = tuple(c.id for c in CAPABILITIES)
FLOOR_IDS = tuple(floor_id for floor_id, _label in FLOOR)
_BY_ID = {c.id: c for c in CAPABILITIES}

# What enforces each row and how strongly, for `carter access -v`:
# id -> (layer, strength). One entry per id; a test pins the keys to the schema. Keep
# layer + strength <= 50 chars so the `-v` line stays under 70.
_DENIES_AND_GATE = ("OpenCode denies, gate", "medium tools, weak shell")
ENFORCED: dict[str, tuple[str, str]] = {
    "workspace_edit": ("OpenCode edit permission", "medium"),
    "run_commands": ("OpenCode shell permission", "medium"),
    "git_commit": ("command gate, git hooks, tier check", "weak"),
    "github_read": ("token scopes, gate", "strong if token is read-only"),
    "pr_write": ("gate flags, ask", "weak; strong if token lacks write"),
    "issue_write": ("gate flags, ask", "weak; strong if token lacks write"),
    "destructive": ("OpenCode command globs", "weak"),
    "infra_apply": ("command globs", "weak; cloud credentials limit it"),
    "opencode_config": ("OpenCode edit deny", "medium; not shell writes"),
    "push": ("no SSH agent, hook", "strong vs token, weak vs keys"),
    "gh_api": ("command gate", "weak"),
    "github_admin": ("command gate", "weak; strong if token lacks scope"),
    "sudo": _DENIES_AND_GATE,
    "secrets": _DENIES_AND_GATE,
    "carter_internals": _DENIES_AND_GATE,
}

# Consent groups whose rules hold floor items up: group -> the floor ids that are open while
# it is missing. `g2` holds `sudo` and `carter_internals` (through the human-only verbs and the
# env overrides); its control paths come from `config-edit`, which has its own line below, as do
# `hooks` (or `repo_hooks`).
GROUP_FLOORS: dict[str, tuple[str, ...]] = {
    "g2": ("push", "gh_api", "github_admin", "sudo", "carter_internals"),
    "read-edit-denies": ("secrets",),
}
# A group that holds no row of the table but a refusal worth saying: group -> what is open.
OFF_NOTES: dict[str, str] = {"docker": "agents may run docker"}
_COMMIT_HOOKS = frozenset({"hooks", "repo_hooks"})  # either one does the job (git version)
_CONFIG_EDIT = "config-edit"


def missing_group_lines(accepted: Iterable[str]) -> tuple[str, ...]:
    """One ``!`` line (<= 60 chars) per consent group that is off: ``! g2 off: <ids>`` names
    the floor rows that are therefore not denied. ``accepted`` is what the guard state records."""
    have = set(accepted)
    lines = [
        f"! {group} off: {', '.join(ids)}"
        for group, ids in GROUP_FLOORS.items()
        if group not in have
    ]
    lines += [f"! {group} off: {note}" for group, note in OFF_NOTES.items() if group not in have]
    if not have & _COMMIT_HOOKS:
        lines.append("! hooks off: agent commits are not checked")
    if _CONFIG_EDIT not in have:
        lines.append("! config-edit off: agents can edit this level")
    return tuple(lines)


def missing_groups_summary(lines: Sequence[str]) -> str:
    """The one line ``carter check`` prints for ``missing_group_lines``; empty when none."""
    count = len(lines)
    if not count:
        return ""
    return f"! {count} guard group{'s' if count != 1 else ''} missing (see: carter access)"


# Roles (D6). Kept here, not imported from `carter.config`, so the renderer can import
# this module; a test pins both sets to `AGENT_ALLOWLIST`.
LOCAL_WRITE_ROLES = frozenset({"pm", "narrator", "engineer", "security", "devops"})
INFRA_ROLES = frozenset({"devops"})

# Token scope names for `warnings`; the token check maps GitHub's names to these.
SCOPE_PULL_REQUESTS = "pull_requests"
SCOPE_ISSUES = "issues"

_CONFIG = "config.toml [access]: "
FALLBACK = "! access config invalid: using strict"
UNREADABLE = "config.toml unreadable or not valid TOML"
UNAVAILABLE = "config.toml [access] was not read"
_LEVEL_HELP = "level must be strict/guarded/relaxed"
_VALUE_HELP = " must be allowed/ask/denied"


@dataclass(frozen=True)
class UserAccess:
    """What the loader read of ``config.toml``: the ``[access]`` table or why there is none."""

    table: Any = None  # the raw table; ``None`` when the file or the table is absent
    error: str | None = None  # the file could not be read or parsed: fail closed


@dataclass(frozen=True)
class Access:
    """The resolved capabilities for one role (or none) and the lines to show."""

    level: str  # the user's level, `strict` after a fallback or when absent
    effective_level: str  # the stricter of the user's and the workspace's level
    level_source: str  # `default` (not set), `config` or `fallback` (an error)
    values: dict[str, str]  # id -> allowed | ask | denied, every adjustable id
    sources: dict[str, str]  # id -> preset | override | workspace | role
    notes: tuple[str, ...]  # validation, deprecation and "can only harden" lines


def _show(key: object) -> str:
    """A config key for a message: control characters escaped, cut at 32."""
    text = "".join(f"\\x{ord(c):02x}" if ord(c) < 32 or ord(c) == 127 else c for c in str(key))
    return text[:32]


def _problem(cap: Capability, value: object) -> str | None:
    """Why ``value`` is no valid override of ``cap``: ``value``, ``max`` or ``None``."""
    if not isinstance(value, str) or value not in RANK:
        return "value"
    return "max" if RANK[value] < RANK[cap.max] else None


def _read_user(table: Any) -> tuple[str, dict[str, str], list[str]]:
    """``(level, overrides, errors)`` of the user's ``[access]``; errors mean fail closed."""
    if table is None:
        return "strict", {}, []
    if not isinstance(table, Mapping):
        return "strict", {}, [f"{_CONFIG}must be a table"]
    level, overrides, errors = "strict", {}, []
    for key, value in table.items():
        if key == "level":
            if isinstance(value, str) and value in LEVELS:
                level = value
            else:
                errors.append(f"{_CONFIG}{_LEVEL_HELP}")
        elif key in _BY_ID:
            problem = _problem(_BY_ID[key], value)
            if problem == "value":
                errors.append(f"{_CONFIG}{key}{_VALUE_HELP}")
            elif problem == "max":
                errors.append(f"{_CONFIG}{key} max is {_BY_ID[key].max}")
            else:
                overrides[key] = value
        elif key in FLOOR_IDS:
            errors.append(f"{_CONFIG}{key} is fixed at never")
        else:
            errors.append(f"{_CONFIG}unknown key '{_show(key)}'")
    return level, overrides, errors


def _read_workspace(
    table: Any, policy_level: Any, user_level: str, user_values: Mapping[str, str]
) -> tuple[dict[str, str], str | None, list[str]]:
    """The workspace's value per id (only the ids it sets), its level and its lines.

    Never raises and never loosens: an invalid row is ``denied``, an invalid level is
    ``strict``, and a value looser than the user's is reported and left to the merge.
    """
    notes: list[str] = []
    rows: dict[str, str] = {}
    levels: list[tuple[str, str]] = []  # (key name, level)

    def add_level(name: str, value: Any) -> None:
        if isinstance(value, str) and value in LEVELS:
            levels.append((name, value))
        else:
            notes.append(f"! carter.yaml {name} invalid: using strict")
            levels.append((name, "strict"))

    if table is not None and not isinstance(table, Mapping):
        notes.append("! carter.yaml access invalid: using strict")
        levels.append(("access.level", "strict"))
        table = {}
    for key, value in (table or {}).items():
        if key == "level":
            add_level("access.level", value)
        elif key in _BY_ID:
            if _problem(_BY_ID[key], value):
                notes.append(f"! carter.yaml access.{key} invalid: using denied")
                rows[key] = "denied"
            else:
                rows[key] = value
                if RANK[value] < RANK[user_values[key]]:
                    notes.append(f"! carter.yaml access.{key} ignored: can only harden")
        else:
            notes.append(f"! carter.yaml access.{_show(key)} unknown: ignored")
    if policy_level is not None:
        notes.append("! carter.yaml policy.level is deprecated: use access.level")
        add_level("policy.level", policy_level)

    for name, level in levels:
        if LEVELS.index(level) > LEVELS.index(user_level):
            notes.append(f"! carter.yaml {name} ignored: can only harden")
    strictest = min((level for _name, level in levels), key=LEVELS.index, default=None)
    if strictest:  # the stricter of the two keys; an explicit row replaces its preset
        for cap in CAPABILITIES:
            rows.setdefault(cap.id, cap.preset(strictest))
    return rows, strictest, notes


def _role_cap(role: str | None, cap_id: str) -> str:
    """The loosest value ``role`` may hold for ``cap_id`` (``allowed`` = no cap)."""
    if role is None:
        return "allowed"
    if cap_id == "infra_apply" and role not in INFRA_ROLES:
        return "denied"
    if cap_id == "destructive" and role not in LOCAL_WRITE_ROLES:
        return "denied"
    if cap_id in ("pr_write", "issue_write") and role not in LOCAL_WRITE_ROLES:
        return "ask"  # a read-only role asks before it writes anywhere, at every level
    return "allowed"


def resolve(
    user: Any = None,
    workspace: Any = None,
    workspace_policy_level: Any = None,
    role: str | None = None,
    user_error: str | None = None,
) -> Access:
    """The effective access for ``role`` (``None``: no role cap, as ``carter access`` shows).

    ``user`` is ``[access]`` from ``config.toml`` and ``workspace`` is ``access:`` from
    ``carter.yaml``, both ``None`` when absent. ``workspace_policy_level`` is the
    deprecated ``policy.level`` of ``carter.yaml`` (same merge, one deprecation line).
    ``user_error`` says ``config.toml`` could not be read: strict, with that line.
    """
    level, overrides, errors = _read_user(user)
    if user_error:
        errors.append(user_error)
    if errors:
        level, overrides = "strict", {}
        notes = [*errors, FALLBACK]
        level_source = "fallback"
    else:
        notes = []
        level_source = "config" if isinstance(user, Mapping) and "level" in user else "default"

    user_values = {c.id: overrides.get(c.id, c.preset(level)) for c in CAPABILITIES}
    ws_rows, ws_level, ws_notes = _read_workspace(
        workspace, workspace_policy_level, level, user_values
    )
    effective = min(filter(None, (level, ws_level)), key=LEVELS.index)

    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    for cap in CAPABILITIES:
        # Ties go to the first candidate, so a source is named only when it changed the value.
        candidates = [
            (user_values[cap.id], "override" if cap.id in overrides else "preset"),
            (ws_rows.get(cap.id, "allowed"), "workspace"),
            (_role_cap(role, cap.id), "role"),
        ]
        values[cap.id], sources[cap.id] = max(candidates, key=lambda c: RANK[c[0]])
    return Access(level, effective, level_source, values, sources, (*notes, *ws_notes))


def resolve_config(config: Mapping[str, Any], role: str | None = None) -> Access:
    """``resolve`` for a loaded ``carter.yaml`` dict: the one call every reader makes.

    The user's side comes from ``config["access_user"]`` (``carter.config.with_user_access``);
    without it the user has no ``[access]`` and the level is ``strict``. Only a real
    ``UserAccess`` counts: anything else (a ``carter.yaml`` that names the key) is strict.
    """
    user = config.get("access_user")
    if user is None:
        user = UserAccess()
    elif not isinstance(user, UserAccess):
        user = UserAccess(error=UNAVAILABLE)
    policy = config.get("policy") or {}
    level = policy.get("level") if isinstance(policy, Mapping) else None
    return resolve(user.table, config.get("access"), level, role, user_error=user.error)


def warnings(access: Access, *, token_writes: Iterable[str] = ()) -> tuple[str, ...]:
    """Token facts the user should see next to the table: one `!` line each, as data.

    ``token_writes`` are the write scopes of the agent token (``SCOPE_*``). Missing consent
    groups have their own lines (``missing_group_lines``). The resolver does not print them.
    """
    scopes = set(token_writes)
    lines = []
    if SCOPE_PULL_REQUESTS in scopes:
        lines.append("! token can approve PRs: github_admin is text-gated")
    if SCOPE_ISSUES in scopes and access.values["issue_write"] != "allowed":
        lines.append("! token has Issues: write: issue_write is text-gated")
    return tuple(lines)
