"""Schema-2 names for ``~/.carter/config.toml`` (RFC-0007 §4.1), in one place.

Every table and key name lives here and nowhere else: a TOML key is the name of the
dataclass field that holds it, and the tables are listed in ``SECTIONS``. Renaming a
key (the architect review in plan 002 step 7 may do so) is a one-line change in this
module; the reader, the resolver and ``schema_names()`` derive from it.

Stdlib-only. Pure data: nothing here reads a file.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Literal

SCHEMA_VERSION = 2
KEY_SCHEMA = "schema"  # top-level integer

ROLES = ("co-author", "author")  # a | b (RFC §4.1 roles)
TIERS = ("t0", "t1", "t2")
# Values legal *in the file*. An optional key that is unset is omitted from the file; an
# explicit "" is E-CONFIG. In memory "" is the "unset" marker (the dataclass default).
CAP_TIERS = ("t0", "t1")  # [workspaces.*] max_tier (D64)
REQUIRE_TIERS = ("t0", "t1", "t2")  # [workspaces.*] require_tier (D62)
OPTIONAL_ROLES = ROLES  # a pinned workspace role
SIGNING_FORMATS = ("ssh",)  # v1: ssh only


def _choice(default: Any, choices: tuple[str, ...]) -> Any:
    return field(default=default, metadata={"choices": choices})


@dataclass(frozen=True)
class Identity:
    """``[identity]``: who the LLM is (BYO machine account)."""

    role: str = _choice("co-author", ROLES)
    login: str = ""
    id: int = 0  # numeric GitHub id, from GET /users/<login>
    name: str = ""
    email: str = ""  # <id>+<login>@users.noreply.github.com
    mode: str = ""  # CI mode override


@dataclass(frozen=True)
class Signing:
    """``[identity.signing]``: public material and a private-key *path* (never content)."""

    format: str = _choice("ssh", SIGNING_FORMATS)
    public_key_path: str = ""
    public_key: str = ""  # "type blob"; never expanduser'd
    fingerprint: str = ""
    private_key_path: str = ""
    previous_public_keys: tuple[str, ...] = ()
    agent_socket: str = ""
    program: str = ""
    ttl: str = "8h"
    ssh_bin_dir: str = "/usr/bin"  # Apple OpenSSH; Homebrew users override (RFC §4.6)


@dataclass(frozen=True)
class Disclosure:
    """``[identity.disclosure]``."""

    assisted_by: bool = False


@dataclass(frozen=True)
class Attribution:
    """``[attribution]``: non-identity text, kept from schema 1."""

    footer: str = "_This comment was generated with Carter._"


@dataclass(frozen=True)
class Github:
    """``[github]``."""

    read_token_file: str = ""
    probe_repo: str = ""  # optional "owner/name" for the token write probe (never printed)


@dataclass(frozen=True)
class Workspace:
    """``[workspaces."<abs path>"]``: per-workspace controls and pinned policy."""

    allow_project_opencode_edit: bool = False  # D52
    max_tier: str = _choice("", CAP_TIERS)  # D64 cap
    role: str = _choice("", OPTIONAL_ROLES)  # pinned by `carter update` (D62)
    require_tier: str = _choice("", REQUIRE_TIERS)  # pinned by `carter update` (D62)


# attribute on ``IdentityConfig`` -> (TOML table path, dataclass). ``workspaces`` is a
# map of such tables and is handled separately.
SECTIONS: tuple[tuple[str, tuple[str, ...], type], ...] = (
    ("identity", ("identity",), Identity),
    ("signing", ("identity", "signing"), Signing),
    ("disclosure", ("identity", "disclosure"), Disclosure),
    ("attribution", ("attribution",), Attribution),
    ("github", ("github",), Github),
)
TABLE_WORKSPACES = "workspaces"
WORKSPACE_PLACEHOLDER = '"<abs path>"'

State = Literal["absent", "current", "needs_migration"]


@dataclass(frozen=True)
class IdentityConfig:
    """A parsed ``config.toml``. ``state`` says how to treat it (see ``config.py``)."""

    identity: Identity = field(default_factory=Identity)
    signing: Signing = field(default_factory=Signing)
    disclosure: Disclosure = field(default_factory=Disclosure)
    attribution: Attribution = field(default_factory=Attribution)
    github: Github = field(default_factory=Github)
    workspaces: dict[str, Workspace] = field(default_factory=dict)
    schema: int = SCHEMA_VERSION
    state: State = "absent"
    unknown_keys: tuple[str, ...] = ()  # dotted paths the writer does not model

    @property
    def needs_migration(self) -> bool:
        """True for a schema-1 file: nothing in it is interpreted as identity."""
        return self.state == "needs_migration"


def schema_names() -> dict[str, tuple[str, ...]]:
    """Every modelled table (dotted path) with its keys, for the step-7 review and the
    frozen-names snapshot test."""
    names: dict[str, tuple[str, ...]] = {"": (KEY_SCHEMA,)}
    for _attr, path, cls in SECTIONS:
        names[".".join(path)] = tuple(f.name for f in fields(cls))
    names[f"{TABLE_WORKSPACES}.{WORKSPACE_PLACEHOLDER}"] = tuple(f.name for f in fields(Workspace))
    return names
