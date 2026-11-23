"""The only config writer: ``config-managed.toml``. ``config.toml`` is never opened for writing.

It stores the keys Carter derives (``managed.OWNED`` and the pins) when they differ from the
defaults, and checks that the reader gives them back. A table that ``config.toml`` also sets
is the human's: a change to it is refused, an equal one is skipped. Writes are atomic (temp
file in the same directory, fsync, ``os.replace``, mode 0600) and refuse a symlink at the
path or in its parent.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import Any

from carter.identity.config import (
    ConfigError,
    default_path,
    load_identity,
    parse_identity,
    read_document,
)
from carter.identity.managed import (
    HEADER,
    OWNED,
    PIN_KEYS,
    PINS,
    WORKSPACES,
    held,
    is_link,
    managed_path,
    merge,
    table,
)
from carter.identity.schema import SECTIONS, IdentityConfig

_ESC = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


class WriterError(Exception):
    """The managed file cannot be written safely; nothing was changed."""


def _str(value: str) -> str:
    def esc(c: str) -> str:
        if c in _ESC:
            return _ESC[c]
        return f"\\u{ord(c):04x}" if ord(c) < 0x20 or ord(c) == 0x7F else c

    return '"' + "".join(esc(c) for c in value) + '"'


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _str(value)
    return "[" + ", ".join(_str(v) for v in value) + "]"  # tuple[str, ...]


def owned(cfg: IdentityConfig) -> dict[str, dict[str, Any]]:
    """The values of ``cfg`` that Carter owns and that differ from the defaults, by dotted
    table name (``identity.signing``) and, for pins, ``pins.<path>``."""
    out: dict[str, dict[str, Any]] = {}
    for attr, path, cls in SECTIONS:
        obj = getattr(cfg, attr)
        vals = {
            f.name: getattr(obj, f.name)
            for f in fields(cls)
            if f.name in OWNED.get(path, ()) and getattr(obj, f.name) != f.default
        }
        if vals:
            out[".".join(path)] = vals
    for ws, w in cfg.workspaces.items():
        pin = {k: getattr(w, k) for k in PIN_KEYS if getattr(w, k)}
        if pin:
            out[f"{PINS}.{ws}"] = pin
    return out


def dumps(doc: dict[str, dict[str, Any]]) -> str:
    """``doc`` (the shape ``owned`` returns) as TOML, under the one-line header."""
    out = [HEADER]
    for name, vals in doc.items():
        if name.startswith(f"{PINS}."):
            name = f"{PINS}.{_str(name[len(PINS) + 1 :])}"
        out += ["", f"[{name}]", *(f"{k} = {_value(v)}" for k, v in vals.items())]
    return "\n".join(out) + "\n"


def _checked(doc: dict[str, Any]) -> str:
    """``dumps`` plus proof that the reader gives ``doc`` back."""
    text = dumps(doc)
    try:
        back = parse_identity(merge(None, tomllib.loads(text))[0] or None)
    except (ConfigError, tomllib.TOMLDecodeError) as exc:
        raise WriterError("refusing to write an invalid config-managed.toml") from exc
    if owned(back) != doc:
        raise WriterError("refusing to write: config-managed.toml does not round trip")
    return text


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _without_human_tables(
    new: dict[str, dict[str, Any]], old: dict[str, dict[str, Any]], human: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """``new`` minus the tables ``config.toml`` sets; a change to one of them is refused."""
    new = dict(new)
    names = [(".".join(path), table(human, path), keys) for path, keys in OWNED.items()]
    names += [
        (f"{PINS}.{ws}", entry, PIN_KEYS) for ws, entry in table(human, (WORKSPACES,)).items()
    ]
    for name, theirs, keys in names:
        if held(theirs, keys):
            if new.get(name) != old.get(name):
                where = "workspaces" if name.startswith(PINS) else name.split(".")[0]
                raise WriterError(f"config.toml sets [{where}]: edit it there")
            new.pop(name, None)
    return new


def write_managed(cfg: IdentityConfig, config_path: Path | None = None) -> bool:
    """Store the owned part of ``cfg`` next to ``config_path``. ``False`` if nothing changed.

    Raises ``ConfigError`` for a broken ``config.toml``, ``WriterError`` for a symlink, or a
    change to a table that ``config.toml`` sets.
    """
    config_path = config_path or default_path()
    target = managed_path(config_path)
    old = owned(load_identity(config_path))
    new = _without_human_tables(owned(cfg), old, read_document(config_path) or {})
    if is_link(target):
        raise WriterError("config-managed.toml or its folder is a symlink")
    if not new:
        if not target.exists():
            return False
        target.unlink()
        return True
    text = _checked(new)
    try:
        if target.read_text(encoding="utf-8") == text:
            target.chmod(0o600)
            return False
    except (OSError, ValueError):
        pass
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if is_link(target):
        raise WriterError("config-managed.toml or its folder is a symlink")
    _atomic_write(target, text)
    return True
