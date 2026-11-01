"""Explicit migration of ``~/.carter/config.toml`` from schema 1 to schema 2.

Mapping (RFC-0007 App A §6): ``[attribution] name/email`` move to ``[identity]`` only if
the email is ``<id>+<login>@users.noreply.github.com`` (the old ``carter-bot@`` default
is dropped, which is T0); ``[attribution] footer`` is kept verbatim; ``[git] signing_key``
is dropped (it was the human's key); everything else stays only in the backup.

Only the installer calls this, never a read path. The original is copied to
``config.toml.schema1.bak`` first and that backup is never overwritten; the new file is
written atomically (see ``writer.py``), so a failure leaves the original intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from carter.identity.config import default_path, parse_identity, read_document
from carter.identity.resolve import is_noreply_email
from carter.identity.schema import Attribution, Identity, IdentityConfig
from carter.identity.writer import write_config

BACKUP_NAME = "config.toml.schema1.bak"
Status = Literal["absent", "created", "migrated", "current"]
_MAPPED = {"attribution": {"name", "email", "footer"}, "git": {"signing_key"}}


class MigrationError(Exception):
    """The migration was refused; nothing was changed."""


@dataclass(frozen=True)
class MigrationResult:
    status: Status
    warnings: tuple[str, ...] = ()
    backup: Path | None = None


def _text(table: dict[str, Any], key: str, warnings: list[str]) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        warnings.append(f"[attribution] {key} is not a string; dropped (kept in the backup)")
        return None
    return value


def map_schema1(doc: dict[str, Any]) -> tuple[IdentityConfig, tuple[str, ...]]:
    """Pure mapping of a parsed schema-1 document to a schema-2 config plus warnings.

    Warnings name keys, never values (a path or address could identify the user).
    """
    warnings: list[str] = []
    attribution = doc.get("attribution")
    attribution = attribution if isinstance(attribution, dict) else {}
    name = _text(attribution, "name", warnings)
    email = _text(attribution, "email", warnings)
    footer = _text(attribution, "footer", warnings)

    identity = Identity()
    if email and is_noreply_email(email):
        user_id, _, rest = email.partition("+")
        identity = Identity(
            login=rest.partition("@")[0], id=int(user_id), name=name or "", email=email
        )
    elif email:
        warnings.append(
            "[attribution] email is not <id>+<login>@users.noreply.github.com; "
            "dropped, so the identity is T0"
        )

    git = doc.get("git")
    if isinstance(git, dict) and git.get("signing_key"):
        warnings.append("[git] signing_key dropped: Carter never uses the human's signing key")

    leftovers: list[str] = []
    for table, keys in doc.items():
        if table == "schema":
            continue
        if not isinstance(keys, dict):
            leftovers.append(table)
            continue
        leftovers += [f"{table}.{k}" for k in keys if k not in _MAPPED.get(table, set())]
    if leftovers:
        warnings.append(
            f"not carried over (kept only in the backup): {', '.join(sorted(leftovers))}"
        )

    cfg = IdentityConfig(
        identity=identity,
        attribution=Attribution(footer) if footer is not None else Attribution(),
        state="current",
    )
    return cfg, tuple(warnings)


def migrate_config(path: Path | None = None) -> MigrationResult:
    """Migrate ``path`` if it is a schema-1 file. Raises ``ConfigError`` (E-CONFIG) for a
    file that does not parse or has an unsupported schema; ``MigrationError`` if a backup
    of a different file is already in the way."""
    path = path or default_path()
    doc = read_document(path)
    if doc is None:
        return MigrationResult("absent")
    if not parse_identity(doc).needs_migration:
        return MigrationResult("current")  # empty, schema 2 (or ConfigError for others)
    cfg, warnings = map_schema1(doc)
    backup = path.with_name(BACKUP_NAME)
    if backup.exists() and backup.read_bytes() != path.read_bytes():
        raise MigrationError(
            f"{BACKUP_NAME} already exists and differs from config.toml; move it aside and re-run"
        )
    write_config(cfg, path, backup_to=backup)
    return MigrationResult("migrated", warnings, backup)


def ensure_config(path: Path | None = None) -> MigrationResult:
    """Installer entry: create schema-2 defaults if there is no file, migrate schema 1,
    leave schema 2 alone."""
    path = path or default_path()
    result = migrate_config(path)
    if result.status != "absent":
        return result
    write_config(IdentityConfig(state="current"), path)
    return MigrationResult("created")
