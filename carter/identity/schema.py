"""Schema-2 names for ``~/.carter/config.toml``, in one place.

Every table and key name lives here and nowhere else: a TOML key is the name of the
dataclass field that holds it, and the tables are listed in ``SECTIONS``. Renaming a
key is a one-line change in this
module; the reader, the resolver and ``schema_names()`` derive from it.

Stdlib-only. Pure data: nothing here reads a file.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Literal

SCHEMA_VERSION = 2
KEY_SCHEMA = "schema"  # top-level integer

ROLES = ("co-author", "author")
TIERS = ("t0", "t1", "t2")
# Values legal *in the file*. An optional key that is unset is omitted from the file; an
# explicit "" is E-CONFIG. In memory "" is the "unset" marker (the dataclass default).
CAP_TIERS = ("t0", "t1")  # [workspaces.*] max_tier
REQUIRE_TIERS = ("t0", "t1", "t2")  # [workspaces.*] require_tier
OPTIONAL_ROLES = ROLES  # a pinned workspace role
SIGNING_FORMATS = ("ssh",)  # v1: ssh only
SIGNING_MODES = ("file", "agent")  # sign from the key file, or through the agent


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
    ttl: str = ""  # no lifetime unless `unlock --ttl` or this key says so
    mode: str = _choice("", SIGNING_MODES)  # "file" = a key without passphrase, signed in place
    ssh_bin_dir: str = "/usr/bin"  # Apple OpenSSH; Homebrew users override


@dataclass(frozen=True)
class Disclosure:
    """``[identity.disclosure]``."""

    assisted_by: bool = False


@dataclass(frozen=True)
class Attribution:
    """``[attribution]``: non-identity text."""

    footer: str = "_This comment was generated with Carter._"


@dataclass(frozen=True)
class Github:
    """``[github]``."""

    read_token_file: str = ""
    probe_repo: str = ""  # optional "owner/name" for the token write probe (never printed)


@dataclass(frozen=True)
class Broker:
    """``[broker]``: the approval dwell. Optional.

    ``min_dwell_ms`` can only be raised: the effective value is at least 500 ms.
    There is deliberately no home key: the broker's child ``HOME`` and the ``~/.ssh/config`` scan
    come from the system account entry; a ``[broker] home`` in the file is an unknown key
    and is ignored."""

    min_dwell_ms: int = 500


@dataclass(frozen=True)
class Workspace:
    """``[workspaces."<abs path>"]``: per-workspace controls and pinned policy."""

    allow_project_opencode_edit: bool = False
    max_tier: str = _choice("", CAP_TIERS)  # cap
    role: str = _choice("", OPTIONAL_ROLES)  # pinned by `carter update`
    require_tier: str = _choice("", REQUIRE_TIERS)  # pinned by `carter update`


# attribute on ``IdentityConfig`` -> (TOML table path, dataclass). ``workspaces`` is a
# map of such tables and is handled separately.
SECTIONS: tuple[tuple[str, tuple[str, ...], type], ...] = (
    ("identity", ("identity",), Identity),
    ("signing", ("identity", "signing"), Signing),
    ("disclosure", ("identity", "disclosure"), Disclosure),
    ("attribution", ("attribution",), Attribution),
    ("github", ("github",), Github),
    ("broker", ("broker",), Broker),
)
TABLE_WORKSPACES = "workspaces"
WORKSPACE_PLACEHOLDER = '"<abs path>"'

State = Literal["absent", "current"]


@dataclass(frozen=True)
class IdentityConfig:
    """A parsed ``config.toml``. ``state`` says how to treat it (see ``config.py``)."""

    identity: Identity = field(default_factory=Identity)
    signing: Signing = field(default_factory=Signing)
    disclosure: Disclosure = field(default_factory=Disclosure)
    attribution: Attribution = field(default_factory=Attribution)
    github: Github = field(default_factory=Github)
    broker: Broker = field(default_factory=Broker)
    workspaces: dict[str, Workspace] = field(default_factory=dict)
    schema: int = SCHEMA_VERSION
    state: State = "absent"
    unknown_keys: tuple[str, ...] = ()  # dotted paths the writer does not model


def schema_names() -> dict[str, tuple[str, ...]]:
    """Every modelled table (dotted path) with its keys, for the frozen-names snapshot test."""
    names: dict[str, tuple[str, ...]] = {"": (KEY_SCHEMA,)}
    for _attr, path, cls in SECTIONS:
        names[".".join(path)] = tuple(f.name for f in fields(cls))
    names[f"{TABLE_WORKSPACES}.{WORKSPACE_PLACEHOLDER}"] = tuple(f.name for f in fields(Workspace))
    return names
