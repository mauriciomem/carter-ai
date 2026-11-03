"""The static shell-isolation block as data: rendered at install, validated, hashed.

RFC-0007 §4.5 and App C.2 (plan 004 step 11, frozen as G4). ``carter guard install`` renders
``~/.carter/isolation.json`` with ``render()``, writes the canonical bytes and records their
sha256; the TypeScript plugin only reads that file (it holds no list of its own) and refuses to
create an agent shell when the file is missing, invalid or does not match its baked hash.

Nothing here reads a secret or the identity: the block is the same for every tier. The GitHub
read token is put into ``GH_TOKEN`` by the plugin at shell creation, never into this file.

Stdlib-only, like the rest of ``carter.identity``.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from typing import Any

from carter.identity.errors import E_FALSE_MISSING, IdentityError
from carter.identity.isolation_schema import SCHEMA_VERSION, validate
from carter.identity.rules import load_rules, plugin_defaults

FALSE_CANDIDATES = ("/usr/bin/false", "/bin/false")
GIT_SSH_COMMAND = (
    "ssh -F /dev/null -o IdentityAgent=none -o IdentitiesOnly=yes "
    "-o IdentityFile=/dev/null -o BatchMode=yes"
)
# The URL-scoped github.com helper (OQ-14): the token is read from $GH_TOKEN when git asks,
# so it never appears in a config value.
GITHUB_HELPER = (
    '!f(){ test "$1" = get && printf \'username=x-access-token\\npassword=%s\\n\' "$GH_TOKEN"; }; f'
)
GITHUB_FORMS = ("https://github.com/", "git@github.com:", "ssh://git@github.com/")
GPG_PROGRAMS = ("gpg.program", "gpg.openpgp.program", "gpg.x509.program", "gpg.ssh.program")
BLOCKING_GIT_CONFIG = [["commit.gpgsign", "true"], ["gpg.format", "ssh"]]
# Variables the plugin itself sets or removes on top of `env.set` / `env.delete`.
PLUGIN_SET_VARS = ("GH_TOKEN", "GIT_CONFIG_COUNT")


def resolve_false(stat_fn: Callable[[str], os.stat_result] = os.stat) -> str:
    """First of ``/usr/bin/false``, ``/bin/false`` that is root-owned and not writable by others.

    Never found through the command search path and never a Carter-owned script (an agent could
    edit it, C.2.1). ``stat_fn`` is injectable so tests can fake a macOS layout."""
    for candidate in FALSE_CANDIDATES:
        try:
            st = stat_fn(candidate)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022:
            return candidate
    raise IdentityError(E_FALSE_MISSING)


def git_config_entries(false_path: str) -> list[list[str]]:
    """The ``GIT_CONFIG_*`` entries in C.2 order: reset first, so the helper chain is ours only."""
    entries = [
        ["credential.helper", ""],
        ["credential.https://github.com.helper", GITHUB_HELPER],
        ["url.https://github.com/.insteadOf", "git@github.com:"],
        ["url.https://github.com/.insteadOf", "ssh://git@github.com/"],
    ]
    entries += [["url.no_push://.pushInsteadOf", form] for form in GITHUB_FORMS]
    entries += [["remote.origin.pushurl", "no_push"], ["commit.gpgsign", "false"]]  # C7, D51
    entries += [[program, false_path] for program in GPG_PROGRAMS]  # rv2-sec B1
    return entries


def pollution_pairs(home: str, false_path: str = "/usr/bin/false") -> list[tuple[str, str]]:
    """The entries that identify an environment Carter already isolated: all but the generic ones.

    ``credential.helper=`` and ``commit.gpgsign=false`` are common user choices, so they are not
    markers; the rest are Carter's exact strings."""
    del home  # the pairs hold no path of the user's; kept for a symmetric signature
    return [(k, v) for k, v in git_config_entries(false_path) if v not in ("", "false")]


def render(
    *,
    home: str,
    python_path: str,
    carter_path: str,
    false_path: str,
    pat_file: str = "",
    declined_groups: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The ``isolation.json`` document (keys sorted at every level; lists keep their order)."""
    rules = load_rules()
    markers = [
        [m.name, m.match, m.value.replace("<home>", home)]
        for m in rules.isolation_markers
        if m.match in ("contains", "equals")
    ]
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "env": {
            "set": {
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
                "GH_CONFIG_DIR": f"{home}/.carter/run/gh-empty",
                "GH_NO_UPDATE_NOTIFIER": "1",
                "GIT_ASKPASS": false_path,
                "GIT_SSH_COMMAND": GIT_SSH_COMMAND,
                "GIT_TERMINAL_PROMPT": "0",
                "SSH_ASKPASS_REQUIRE": "never",
            },
            "delete": ["SSH_AUTH_SOCK", "GITHUB_TOKEN", "GIT_CONFIG_PARAMETERS"],
        },
        "git_config": git_config_entries(false_path),
        "blocking_git_config": BLOCKING_GIT_CONFIG,
        "pollution": {
            "agent_signals": list(rules.agent_signals),
            "human_signals": list(rules.human_signals),
            "markers": {
                "env": markers,
                "git_config": [list(p) for p in pollution_pairs(home, false_path)],
            },
        },
        "plugin": {
            **{k: v for k, v in plugin_defaults().items() if k != "status_dir"},
            "python_path": python_path,
            "carter_path": carter_path,
            "pat_file": pat_file,
            "declined_groups": sorted(declined_groups),
            "status_dir": f"{home}/.carter/{plugin_defaults()['status_dir']}",
        },
    }
    validate(doc)
    return json.loads(canonical_bytes(doc))  # keys sorted at every level


def canonical_bytes(doc: Mapping[str, Any]) -> bytes:
    """Deterministic bytes: sorted keys, fixed separators, UTF-8, one trailing newline."""
    return (
        json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def isolation_vars() -> list[str]:
    """Every variable name the block sets or deletes (``isolation_vars`` in ``g2_rules.json``)."""
    doc = render(home="/h", python_path="/p", carter_path="/c", false_path="/usr/bin/false")
    return sorted({*doc["env"]["set"], *doc["env"]["delete"], *PLUGIN_SET_VARS})
