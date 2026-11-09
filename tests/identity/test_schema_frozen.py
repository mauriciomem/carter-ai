"""The schema-2 names are frozen. Changing this file is deliberate:
a rename or a new default needs an architect review and a writer/migration update."""

from __future__ import annotations

from dataclasses import fields

from carter.identity import schema
from carter.identity.schema import (
    Attribution,
    Broker,
    Disclosure,
    Github,
    Identity,
    Signing,
    Workspace,
    schema_names,
)

FROZEN_NAMES = {
    "": ("schema",),
    "identity": ("role", "login", "id", "name", "email", "mode"),
    "identity.signing": (
        "format",
        "public_key_path",
        "public_key",
        "fingerprint",
        "private_key_path",
        "previous_public_keys",
        "agent_socket",
        "program",
        "ttl",
        "mode",
        "ssh_bin_dir",
    ),
    "identity.disclosure": ("assisted_by",),
    "attribution": ("footer",),
    "github": ("read_token_file", "probe_repo"),
    "broker": ("min_dwell_ms",),  # slice B optional table)
    'workspaces."<abs path>"': (
        "allow_project_opencode_edit",
        "max_tier",
        "role",
        "require_tier",
    ),
}

# key -> (default, allowed values in the file or None). "" means "unset" in memory only.
FROZEN_SPEC = {
    Identity: {
        "role": ("co-author", ("co-author", "author")),
        "login": ("", None),
        "id": (0, None),
        "name": ("", None),
        "email": ("", None),
        "mode": ("", None),
    },
    Signing: {
        "format": ("ssh", ("ssh",)),
        "public_key_path": ("", None),
        "public_key": ("", None),
        "fingerprint": ("", None),
        "private_key_path": ("", None),
        "previous_public_keys": ((), None),
        "agent_socket": ("", None),
        "program": ("", None),
        "ttl": ("", None),
        "mode": ("", ("file", "agent")),
        "ssh_bin_dir": ("/usr/bin", None),
    },
    Disclosure: {"assisted_by": (False, None)},
    Attribution: {"footer": ("_This comment was generated with Carter._", None)},
    Github: {"read_token_file": ("", None), "probe_repo": ("", None)},
    Broker: {"min_dwell_ms": (500, None)},
    Workspace: {
        "allow_project_opencode_edit": (False, None),
        "max_tier": ("", ("t0", "t1")),
        "role": ("", ("co-author", "author")),
        "require_tier": ("", ("t0", "t1", "t2")),
    },
}


def test_table_and_key_names_are_frozen() -> None:
    assert schema_names() == FROZEN_NAMES


def test_defaults_and_allowed_values_are_frozen() -> None:
    actual = {
        cls: {
            f.name: (f.default, tuple(f.metadata["choices"]) if "choices" in f.metadata else None)
            for f in fields(cls)
        }
        for cls in FROZEN_SPEC
    }
    assert actual == FROZEN_SPEC


def test_schema_version_is_2() -> None:
    assert schema.SCHEMA_VERSION == 2 and schema.KEY_SCHEMA == "schema"


def test_unset_is_never_a_legal_value_in_the_file() -> None:
    for choices in (schema.CAP_TIERS, schema.REQUIRE_TIERS, schema.OPTIONAL_ROLES, schema.ROLES):
        assert "" not in choices
