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
import json
import os
import stat
import tomllib
from collections.abc import Callable
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
UNSAFE = "config-managed.toml unsafe (owner/mode/link): identity off"
UNREADABLE = "config-managed.toml unreadable: identity off"


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


def read_checked(
    config_path: Path, human: dict[str, Any] | None, parse: Callable[[dict[str, Any] | None], Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """The managed document to merge, or ``None`` (read as empty), and the notes why.

    A failed file check, a value ``parse`` rejects (it raises) or signing values that
    ``identity add`` did not write make the whole file empty: no derived identity is trusted."""
    managed, problem = read_managed(managed_path(config_path))
    if managed is None:
        return None, [problem] if problem else []
    try:
        parse(merge(None, managed)[0] or None)  # a bad value fails the whole file
    except Exception:  # noqa: BLE001 - ConfigError, defined by the caller's module
        return None, [UNREADABLE]
    why = forged_signing(human, managed, config_path.parent)
    return (None, [why]) if why else (managed, [])


ANCHOR = "# private_key_path "  # in allowed_signers: the one value that file keeps as text
SIGNERS = ("hooks", "allowed_signers")  # under the folder of config.toml


def anchor_line(private_key_path: str) -> str:
    """The line ``identity add`` appends to ``allowed_signers`` (a control file, human-only)."""
    return f"{ANCHOR}{json.dumps(private_key_path)}\n" if private_key_path else ""


def forged_signing(human: dict[str, Any] | None, managed: dict[str, Any], folder: Path) -> str:
    """``FORGED`` if the signing values of the managed file are not what ``identity add`` wrote,
    else ``""``. ``allowed_signers`` is the anchor: the current and previous public keys must be
    in it and ``private_key_path`` must be the line ``anchor_line`` wrote. A table that
    ``config.toml`` sets is the human's and is not checked."""
    path = ("identity", "signing")
    mine = table(split(managed)[0], path)
    if held(table(human or {}, path), OWNED[path]):
        return ""
    keys = [k for k in (mine.get("public_key"), *mine.get("previous_public_keys", ())) if k]
    private = mine.get("private_key_path", "")
    if not keys and not private:
        return ""
    try:
        text = folder.joinpath(*SIGNERS).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return FORGED
    lines = text.splitlines()
    have = {" ".join(ln.split()[-2:]) for ln in lines if ln and not ln.startswith("#")}
    if any(" ".join(str(k).split()[:2]) not in have for k in keys):
        return FORGED
    return FORGED if private and anchor_line(private).strip() not in lines else ""
