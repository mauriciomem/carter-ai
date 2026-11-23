"""``~/.carter/config-managed.toml``: what Carter derives. Stdlib-only.

``config.toml`` is yours; this file is Carter's. ``OWNED`` and ``PIN_KEYS`` are the one
table of which keys Carter writes, and the rest of the schema is the human's. Rules:

* a human key in this file is ignored (a planted file cannot loosen a control);
* a table that ``config.toml`` also sets wins, and ``carter check --host`` says so;
* a derived key already in ``config.toml`` (an older install) still loads; Carter never
  moves it;
* any failed file check (symlink, owner, mode, syntax) reads as an empty file.
"""

from __future__ import annotations

import copy
import errno
import os
import stat
import tomllib
from pathlib import Path
from typing import Any

MANAGED_NAME = "config-managed.toml"
HEADER = "# Written by Carter. Edit config.toml instead."

# table path -> keys that Carter derives there
OWNED: dict[tuple[str, ...], tuple[str, ...]] = {
    ("identity",): ("login", "id", "name", "email"),
    ("identity", "signing"): (
        "public_key",
        "fingerprint",
        "private_key_path",
        "mode",
        "previous_public_keys",
        "agent_socket",
        "program",
    ),
    ("github",): ("read_token_file",),
}
PINS = "pins"  # [pins."<abs path>"] holds the keys below
PIN_KEYS = ("role", "require_tier")
WORKSPACES = "workspaces"  # where the reader puts a pin

FORGED = "config-managed.toml ignored: allowed_signers does not match"
UNSAFE = "config-managed.toml ignored: unsafe (owner, mode or link)"
UNREADABLE = "config-managed.toml ignored: unreadable or invalid"
# the notes that mean the file was not used, each with what to do (an identity kept in
# config.toml, from an older install, still loads: the notes do not say "identity off")
IGNORED = {
    UNSAFE: "chmod 600 it, make ~/.carter a real folder, or run `carter identity add`",
    UNREADABLE: "Run `carter identity add` to write it again",
    FORGED: "Run `carter identity add` to write both files again",
}


def managed_path(config_path: Path) -> Path:
    return config_path.with_name(MANAGED_NAME)


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.parent.is_symlink()


def read_managed(path: Path) -> tuple[dict[str, Any] | None, str]:
    """``(document, "")``; ``(None, "")`` if absent; ``(None, why)`` if a check failed.

    Opens with ``O_NOFOLLOW`` and checks the open descriptor (no swap between check and
    read): a regular file, owned by this user, with no group or other bits.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None, ""
    except OSError as exc:
        return None, UNSAFE if exc.errno == errno.ELOOP else UNREADABLE
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            return None, UNSAFE
        if info.st_mode & 0o077 or path.parent.is_symlink():
            return None, UNSAFE
        with os.fdopen(fd, "rb", closefd=False) as fh:
            return tomllib.loads(fh.read().decode("utf-8")), ""
    except (OSError, ValueError):  # TOMLDecodeError and UnicodeDecodeError are ValueErrors
        return None, UNREADABLE
    finally:
        os.close(fd)


def _leaves(node: dict[str, Any], path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    out: list[tuple[tuple[str, ...], Any]] = []
    for key, value in node.items():
        if isinstance(value, dict):
            out += _leaves(value, (*path, key))
        else:
            out.append(((*path, key), value))
    return out


def _is_owned(path: tuple[str, ...]) -> bool:
    if len(path) == 3 and path[0] == PINS:
        return path[2] in PIN_KEYS
    return path[-1] in OWNED.get(path[:-1], ())


def split(doc: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The part of ``doc`` this file may hold, and the dotted names that were ignored."""
    kept: dict[str, Any] = {}
    ignored: list[str] = []
    for path, value in _leaves(doc):
        if not _is_owned(path):
            ignored.append(".".join(path))
            continue
        node = kept
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value
    return kept, ignored


def _more(names: list[str]) -> str:
    return names[0] + (f" +{len(names) - 1} more" if len(names) > 1 else "")


def table(doc: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    node: Any = doc
    for part in path:
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def held(node: dict[str, Any], keys: tuple[str, ...]) -> bool:
    """True if the human's table sets any key that Carter would derive."""
    return any(k in node for k in keys)


def merge(
    human: dict[str, Any] | None, managed: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """One document for the reader, and the notes ``check --host`` prints."""
    kept, ignored = split(managed)
    notes = [f"config-managed.toml: {_more(ignored)} is not Carter's, ignored"] if ignored else []
    doc = copy.deepcopy(human or {})
    wins: list[str] = []

    def put(node: dict[str, Any], mine: dict[str, Any], keys: tuple[str, ...], name: str) -> None:
        if held(node, keys):
            wins.append(name)
        else:
            node.update(mine)

    for path, keys in OWNED.items():
        mine = {k: v for k, v in table(kept, path).items() if not isinstance(v, dict)}
        if mine:
            node = doc
            for part in path:
                child = node.setdefault(part, {})
                if not isinstance(child, dict):  # the reader reports the bad table
                    break
                node = child
            else:
                put(node, mine, keys, ".".join(path))
    pins = table(kept, (PINS,))
    if pins and isinstance(doc.setdefault(WORKSPACES, {}), dict):
        for ws_path, pin in pins.items():
            entry = doc[WORKSPACES].setdefault(ws_path, {})
            if isinstance(entry, dict):
                put(entry, pin, PIN_KEYS, PINS)
    if wins:
        notes.append(f"config.toml wins over config-managed.toml: {_more(sorted(set(wins)))}")
    return doc, notes


LEGACY = "{} from config.toml (legacy; see: carter identity --help)"


def legacy_tables(human: dict[str, Any] | None) -> list[str]:
    """Tables where ``config.toml`` still holds keys that Carter derives (an older install)."""
    doc = human or {}
    names = [".".join(path) for path, keys in OWNED.items() if held(table(doc, path), keys)]
    entries = table(doc, (WORKSPACES,)).values()
    if any(isinstance(e, dict) and held(e, PIN_KEYS) for e in entries):
        names.append(PINS)
    return names
