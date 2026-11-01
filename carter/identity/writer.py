"""Schema-only TOML writer (D55). Only explicit commands call it (migration, install,
``carter update``); read paths never import it.

Serialises exactly the schema-2 model (basic strings, ints, bools, string lists, tables)
and omits unset optional enums instead of writing ``""``. It refuses to lose data
(unmodelled keys, a schema-1 file without a backup, a file that does not parse) and
re-reads its own output through the reader, so it cannot write what the reader rejects.
Writes are atomic: temp file in the same directory, fsync, ``os.replace``, mode 0600.
"""

from __future__ import annotations

import difflib
import os
import re
import tempfile
import tomllib
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from carter.identity.config import ConfigError, default_path, load_identity, parse_identity
from carter.identity.schema import SCHEMA_VERSION, SECTIONS, TABLE_WORKSPACES, IdentityConfig

_BARE = re.compile(r"[A-Za-z0-9_-]+")
_ESC = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
_HEADER = "# Carter configuration (schema 2). Rewritten by carter commands; comments are not kept."


class WriterError(Exception):
    """The config cannot be written safely; nothing was changed."""


class UnmodelledKeysError(WriterError):
    """The existing file holds data the writer would drop; ``diff`` shows the change."""

    def __init__(self, keys: tuple[str, ...], diff: str) -> None:
        super().__init__(f"refusing to rewrite config.toml: it holds unmodelled keys\n{diff}")
        self.keys, self.diff = keys, diff


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


def _body(obj: Any) -> list[str]:
    """``key = value`` lines; an unset optional enum (default ``""``) is left out."""
    return [
        f"{f.name} = {_value(getattr(obj, f.name))}"
        for f in fields(obj)
        if not (getattr(obj, f.name) == "" and f.default == "" and "choices" in f.metadata)
    ]


def dumps(cfg: IdentityConfig) -> str:
    """Serialise ``cfg`` as schema-2 TOML."""
    out = [_HEADER, f"schema = {SCHEMA_VERSION}"]
    for attr, path, _cls in SECTIONS:
        out += ["", "[" + ".".join(path) + "]", *_body(getattr(cfg, attr))]
    for ws_path, ws in cfg.workspaces.items():
        out += ["", f"[{TABLE_WORKSPACES}.{_str(ws_path)}]", *_body(ws)]
    return "\n".join(out) + "\n"


def _core(cfg: IdentityConfig) -> IdentityConfig:
    """``cfg`` without read-time facts (state, unknown keys), for comparison."""
    return replace(cfg, state="current", unknown_keys=())


def _checked(cfg: IdentityConfig) -> str:
    """``dumps`` plus proof that the reader gives ``cfg`` back."""
    text = dumps(cfg)
    try:
        again = parse_identity(tomllib.loads(text))
    except (ConfigError, tomllib.TOMLDecodeError) as exc:
        detail = getattr(exc, "detail", "TOML error")
        raise WriterError(f"refusing to write an invalid config ({detail})") from exc
    if _core(again) != _core(cfg):
        raise WriterError("refusing to write: the config does not survive a round trip")
    return text


def _create_backup(source: Path, backup: Path) -> None:
    """Copy ``source`` to ``backup`` (0600) unless it exists: a backup is never overwritten."""
    try:
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as fh:
        fh.write(source.read_bytes())
        fh.flush()
        os.fsync(fh.fileno())


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


def write_config(
    cfg: IdentityConfig, path: Path | None = None, *, backup_to: Path | None = None
) -> bool:
    """Write ``cfg`` to ``path`` (default ``~/.carter/config.toml``).

    Returns ``False`` when the file already holds exactly this content (nothing written,
    no backup). ``backup_to`` receives a copy of the existing file first, once; a schema-1
    file may only be replaced when it is given. Raises ``ConfigError`` for an unreadable,
    malformed or future-schema file and ``UnmodelledKeysError`` for data that would be lost.
    """
    path = path or default_path()
    new = _checked(cfg)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old is not None:
        existing = load_identity(path)  # raises ConfigError on a broken file
        if existing.unknown_keys or (existing.needs_migration and backup_to is None):
            keys = existing.unknown_keys or ("<schema 1 content>",)
            lines = difflib.unified_diff(
                old.splitlines(), new.splitlines(), "config.toml", "(rewritten)", lineterm=""
            )
            raise UnmodelledKeysError(keys, "\n".join(lines))
        if old == new:
            path.chmod(0o600)
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if old is not None and backup_to is not None:
        _create_backup(path, backup_to)
    _atomic_write(path, new)
    return True
