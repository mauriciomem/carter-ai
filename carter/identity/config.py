"""Read ``~/.carter/config.toml`` with ``tomllib``. Reads never write.

Two entry points with separate failure modes (RFC-0007 §4.1, rv1-eng B5):

* ``load_identity()`` is strict. Anything wrong in a file that exists raises
  ``ConfigError`` (``E-CONFIG``) so callers disable agent commits; it never falls back
  to defaults. A missing or empty file is not an error: that is T0.
* ``load_footer()`` is lenient. The footer is not identity, so a broken file yields the
  default footer plus a warning.

A schema-1 file (no ``schema`` key, or ``schema = 1``) is *recognised*, not read: the
result has ``state == "needs_migration"`` and default (T0) identity. Nothing in it is
reinterpreted as a schema-2 identity.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar, get_type_hints

from carter.home import carter_home
from carter.identity.errors import E_CONFIG, MSG_CONFIG, IdentityError
from carter.identity.schema import (
    KEY_SCHEMA,
    SCHEMA_VERSION,
    SECTIONS,
    TABLE_WORKSPACES,
    Attribution,
    IdentityConfig,
    Workspace,
)

DEFAULT_FOOTER = Attribution().footer
_T = TypeVar("_T")


class ConfigError(IdentityError):
    """``config.toml`` is unreadable, malformed or does not match schema 2."""

    def __init__(self, detail: str) -> None:
        super().__init__(E_CONFIG, MSG_CONFIG, detail)


@dataclass(frozen=True)
class FooterResult:
    """The footer text and, when the file could not be used, why."""

    footer: str
    warning: str | None = None


def default_path() -> Path:
    return carter_home() / "config.toml"


def read_document(path: Path) -> dict[str, Any] | None:
    """Parse the file; ``None`` if it does not exist. Raises ``ConfigError`` otherwise.

    The detail names the failure class and, for TOML errors, tomllib's own message
    (line and column; it does not quote values).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read {path.name}: {type(exc).__name__}") from exc
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML syntax error: {exc}") from exc


def _schema_of(doc: dict[str, Any]) -> int:
    value = doc.get(KEY_SCHEMA, 1)  # no key = schema 1
    if isinstance(value, bool) or not isinstance(value, int) or value not in (1, SCHEMA_VERSION):
        raise ConfigError(f"unsupported {KEY_SCHEMA} value (expected 1 or {SCHEMA_VERSION})")
    return value


def _type_ok(value: Any, hint: Any) -> bool:
    if hint is bool:
        return isinstance(value, bool)
    if hint is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if hint is str:
        return isinstance(value, str)
    return isinstance(value, list) and all(isinstance(v, str) for v in value)  # tuple[str, ...]


def _build(cls: type[_T], table: Any, where: str) -> _T:
    """Instantiate a section from a TOML table, checking types and enum choices."""
    if not isinstance(table, dict):
        raise ConfigError(f"[{where}] must be a table")
    hints = get_type_hints(cls)
    values: dict[str, Any] = {}
    for f in fields(cls):  # type: ignore[arg-type]
        if f.name not in table:
            continue
        value = table[f.name]
        if not _type_ok(value, hints[f.name]):
            raise ConfigError(f"{where}.{f.name} has the wrong type")
        choices = f.metadata.get("choices")
        if choices is not None and value not in choices:
            raise ConfigError(f"{where}.{f.name} is not one of {list(choices)}")
        values[f.name] = tuple(value) if isinstance(value, list) else value
    return cls(**values)


def _dig(doc: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = doc
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node


def _known_tree() -> dict[str, Any]:
    """Nested ``{table: {key: None | subtable}}`` of every modelled name."""
    tree: dict[str, Any] = {KEY_SCHEMA: None}
    for _attr, path, cls in SECTIONS:
        node = tree
        for part in path:
            node = node.setdefault(part, {})
        node.update({f.name: None for f in fields(cls)})
    return tree


def _unknown_keys(doc: dict[str, Any]) -> tuple[str, ...]:
    """Dotted paths in ``doc`` that schema 2 does not model (a rewrite would lose them)."""
    unknown: list[str] = []

    def walk(node: dict[str, Any], known: dict[str, Any], prefix: str) -> None:
        for key, value in node.items():
            if key not in known:
                unknown.append(f"{prefix}{key}")
            elif isinstance(known[key], dict) and isinstance(value, dict):
                walk(value, known[key], f"{prefix}{key}.")

    walk({k: v for k, v in doc.items() if k != TABLE_WORKSPACES}, _known_tree(), "")
    ws_keys = {f.name for f in fields(Workspace)}
    for ws_path, table in doc.get(TABLE_WORKSPACES, {}).items():
        unknown.extend(f"{TABLE_WORKSPACES}.{ws_path}.{k}" for k in table if k not in ws_keys)
    return tuple(unknown)


def load_identity(path: Path | None = None) -> IdentityConfig:
    """Load the identity config. Raises ``ConfigError`` (E-CONFIG) on any defect."""
    return parse_identity(read_document(path or default_path()))


def parse_identity(doc: dict[str, Any] | None) -> IdentityConfig:
    """Build the typed config from a parsed TOML document (``None``/empty = no file)."""
    if not doc:
        return IdentityConfig(state="absent")
    if _schema_of(doc) == 1:
        return IdentityConfig(state="needs_migration", schema=1)

    parts: dict[str, Any] = {
        attr: _build(cls, _dig(doc, p), ".".join(p)) for attr, p, cls in SECTIONS
    }
    raw_ws = doc.get(TABLE_WORKSPACES, {})
    if not isinstance(raw_ws, dict):
        raise ConfigError(f"[{TABLE_WORKSPACES}] must be a table")
    workspaces = {
        key: _build(Workspace, table, f"{TABLE_WORKSPACES}.<path>") for key, table in raw_ws.items()
    }
    return IdentityConfig(
        **parts, workspaces=workspaces, state="current", unknown_keys=_unknown_keys(doc)
    )


def load_footer(path: Path | None = None) -> FooterResult:
    """Load only the footer. Never raises: a broken file degrades to the default."""
    try:
        doc = read_document(path or default_path())
        footer = _build(Attribution, _dig(doc or {}, ("attribution",)), "attribution").footer
    except ConfigError as exc:
        return FooterResult(DEFAULT_FOOTER, f"footer: using the default ({exc.detail})")
    return FooterResult(footer)
