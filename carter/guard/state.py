"""``~/.carter/guard-state.json``: everything Carter owns on the user's machine for G2.

RFC-0007 App C.6.1, freeze F2. It lives apart from ``manifest.json`` so an older installer
(which rebuilds the manifest) can never drop it. It is updated in place: ``load`` →
change → ``save``, never rebuilt from scratch. Unknown top-level keys from a newer Carter
are carried forward. A file that cannot be read, or that has a newer ``schema``, is
refused (``E-STATE-INVALID``) and never overwritten.

No click, jinja2 or CLI imports: read paths (``check``, ``status``) use it too.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from carter.identity.errors import E_STATE_INVALID, IdentityError
from carter.install.atomic import atomic_write_bytes
from carter.install.ownership import sha256_bytes

SCHEMA = 1
STATE_KEYS = (
    "schema", "consents", "files", "gitconfig", "git_config", "opencode_config",
    "opencode_policies", "agent_permissions", "repo_hooks", "guard_version",
)  # fmt: skip
CONSENT_FIELDS = ("decision", "date", "rev")
FILE_FIELDS = ("path", "sha256")
POLICY_FIELDS = ("id", "action", "resource", "effect", "preexisting")
PERMISSION_FIELDS = ("agent", "key", "value", "preexisting")
GITCONFIG_FIELDS = ("file", "key", "value")
GIT_CONFIG_FIELDS = ("file", "key", "value", "scope")
REPO_HOOK_FIELDS = ("path", "sha256")
INCLUDE_KEY = "include.path"
_LISTS = ("files", "git_config", "opencode_policies", "agent_permissions", "repo_hooks")


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text))


def _upsert(items: list[dict], entry: dict, *keys: str) -> None:
    for i, old in enumerate(items):
        if all(old.get(k) == entry[k] for k in keys):
            items[i] = entry
            return
    items.append(entry)


@dataclass
class GuardState:
    schema: int = SCHEMA
    consents: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: list[dict[str, str]] = field(default_factory=list)
    gitconfig: dict[str, str] | None = None
    git_config: list[dict[str, str]] = field(default_factory=list)
    opencode_config: str | None = None
    opencode_policies: list[dict[str, Any]] = field(default_factory=list)
    agent_permissions: list[dict[str, Any]] = field(default_factory=list)
    repo_hooks: list[dict[str, str]] = field(default_factory=list)
    guard_version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # unknown keys, carried forward

    def to_dict(self) -> dict[str, Any]:
        return {**{k: getattr(self, k) for k in STATE_KEYS}, **self.extra}

    # -- consents ------------------------------------------------------------------
    def consent(self, group: str, decision: str, on: str, rev: int = 1) -> None:
        if decision not in ("accepted", "declined"):
            raise ValueError(f"decision must be accepted or declined, got {decision!r}")
        date.fromisoformat(on)  # ValueError unless YYYY-MM-DD
        self.consents[group] = {"decision": decision, "date": on, "rev": rev}

    # -- files and hashes ------------------------------------------------------------
    def record_file(self, path: Path | str, data: bytes) -> None:
        _upsert(self.files, {"path": str(path), "sha256": sha256_bytes(data)}, "path")

    def forget_file(self, path: Path | str) -> None:
        self.files = [f for f in self.files if f["path"] != str(path)]

    def owned_unchanged(self, path: Path | str) -> bool:
        """True only if ``path`` is recorded and still has the recorded hash."""
        recorded = next((f["sha256"] for f in self.files if f["path"] == str(path)), None)
        try:
            return recorded is not None and sha256_bytes(Path(path).read_bytes()) == recorded
        except OSError:  # missing, a directory, unreadable
            return False

    # -- consent offers (D65): a declined re-ask is an additive top-level key ----------------
    def offer(self, group: str) -> dict[str, Any] | None:
        found = (self.extra.get("consent_offers") or {}).get(group)
        return found if isinstance(found, dict) else None

    def record_offer(self, group: str, rev: int, decision: str, on: str) -> None:
        date.fromisoformat(on)
        offers = dict(self.extra.get("consent_offers") or {})
        offers[group] = {"rev": rev, "decision": decision, "date": on}
        self.extra["consent_offers"] = offers

    def clear_offer(self, group: str) -> None:
        offers = {k: v for k, v in (self.extra.get("consent_offers") or {}).items() if k != group}
        if offers:
            self.extra["consent_offers"] = offers
        else:
            self.extra.pop("consent_offers", None)

    # -- per-repo hooks (git < 2.54) --------------------------------------------------
    def record_repo_hook(self, path: Path | str, data: bytes) -> None:
        _upsert(self.repo_hooks, {"path": str(path), "sha256": sha256_bytes(data)}, "path")

    def forget_repo_hook(self, path: Path | str) -> None:
        self.repo_hooks = [h for h in self.repo_hooks if h["path"] != str(path)]

    def repo_hook_unchanged(self, path: Path | str) -> bool:
        """True only if ``path`` is a recorded repo hook with its recorded hash."""
        recorded = next((h["sha256"] for h in self.repo_hooks if h["path"] == str(path)), None)
        try:
            return recorded is not None and sha256_bytes(Path(path).read_bytes()) == recorded
        except OSError:
            return False

    # -- OpenCode config -----------------------------------------------------------
    def record_policy(
        self, id: str, action: str, resource: str, effect: str, *, preexisting: bool
    ) -> None:
        entry = dict(zip(POLICY_FIELDS, (id, action, resource, effect, preexisting), strict=True))
        _upsert(self.opencode_policies, entry, "id")

    def owned_policies(self) -> list[dict[str, Any]]:
        return [p for p in self.opencode_policies if not p["preexisting"]]

    def record_permission(self, agent: str, key: str, value: str, *, preexisting: bool) -> None:
        entry = dict(zip(PERMISSION_FIELDS, (agent, key, value, preexisting), strict=True))
        _upsert(self.agent_permissions, entry, "agent", "key")

    def owned_permissions(self) -> list[dict[str, Any]]:
        return [p for p in self.agent_permissions if not p["preexisting"]]

    # -- git config ----------------------------------------------------------------
    def record_gitconfig(self, file: str, value: str) -> None:
        self.gitconfig = {"file": file, "key": INCLUDE_KEY, "value": value}

    def clear_gitconfig(self) -> None:
        self.gitconfig = None

    def record_git_config(self, file: str, key: str, value: str, scope: str) -> None:
        entry = dict(zip(GIT_CONFIG_FIELDS, (file, key, value, scope), strict=True))
        _upsert(self.git_config, entry, "file", "key")

    # -- version -------------------------------------------------------------------
    def set_guard_version(self, version: str, *, force: bool = False) -> bool:
        """Record the rendered guard version; a lower one never replaces a higher one."""
        if not force and self.guard_version and _version(version) < _version(self.guard_version):
            return False
        self.guard_version = version
        return True


def _invalid(detail: str) -> IdentityError:
    return IdentityError(E_STATE_INVALID, detail=detail)  # key names only, never values


def _dicts(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(i, dict) for i in value)


def _parse(data: object) -> GuardState:
    if not isinstance(data, dict):
        raise _invalid("top level is not an object")
    schema = data.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool):
        raise _invalid("schema")
    if schema > SCHEMA:
        raise _invalid(f"schema {schema} is newer than this Carter understands ({SCHEMA})")
    consents = data.get("consents", {})
    ok = {
        "consents": isinstance(consents, dict)
        and all(isinstance(v, dict) for v in consents.values()),
        "gitconfig": data.get("gitconfig") is None or isinstance(data["gitconfig"], dict),
        "opencode_config": isinstance(data.get("opencode_config"), str | None),
        "guard_version": isinstance(data.get("guard_version"), str | None),
        **{k: _dicts(data.get(k, [])) for k in _LISTS},
    }
    if bad := [k for k, good in ok.items() if not good]:
        raise _invalid(f"wrong type: {', '.join(bad)}")
    known = {k: data[k] for k in STATE_KEYS if k in data}
    return GuardState(**known, extra={k: v for k, v in data.items() if k not in STATE_KEYS})


def load(path: Path) -> GuardState:
    """The state at ``path`` (empty when absent). Raises ``IdentityError(E-STATE-INVALID)``."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return GuardState()
    except (OSError, UnicodeDecodeError) as exc:
        raise _invalid(f"unreadable ({type(exc).__name__})") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _invalid(f"not JSON ({exc.msg})") from exc
    return _parse(data)


@dataclass(frozen=True)
class ReadResult:
    state: GuardState
    status: Literal["absent", "ok", "corrupt", "newer"]
    detail: str = ""


def load_or_empty_readonly(path: Path) -> ReadResult:
    """For read paths (``check``, ``status``): report the problem, never raise or write."""
    if not path.exists():
        return ReadResult(GuardState(), "absent")
    try:
        return ReadResult(load(path), "ok")
    except IdentityError as exc:
        newer = "newer" in exc.detail
        return ReadResult(GuardState(), "newer" if newer else "corrupt", exc.detail)


def save(state: GuardState, path: Path) -> bool:
    """Write atomically (tmp in the same directory, fsync, ``os.replace``), mode 0600.

    Returns False without touching the file when the content is already identical."""
    payload = (json.dumps(state.to_dict(), indent=2) + "\n").encode()
    try:
        if path.read_bytes() == payload:
            return False
    except OSError:
        pass
    atomic_write_bytes(path, payload)
    return True


def quarantine_corrupt(path: Path, *, now: str) -> Path | None:
    """Move a corrupt file to ``<name>.corrupt-<now>`` (human-run ``guard install`` only)."""
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.corrupt-{now}")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{now}.{n}")
        n += 1
    os.replace(path, target)
    return target
