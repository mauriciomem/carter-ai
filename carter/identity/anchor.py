"""The signing values of the managed file are checked against ``allowed_signers``.

``identity add`` writes ``hooks/allowed_signers`` (a control file that only human commands write):
the public keys, and one comment line with ``private_key_path``. A managed file whose signing
values are not in it was not written by ``identity add``, so it reads as empty. Stdlib-only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from carter.identity.managed import (
    FORGED,
    OWNED,
    UNREADABLE,
    held,
    managed_path,
    merge,
    read_managed,
    split,
    table,
)

ANCHOR = "# private_key_path "  # the one value that file keeps as text
SIGNERS = ("hooks", "allowed_signers")  # under the folder of config.toml


def anchor_line(private_key_path: str) -> str:
    """The line ``identity add`` appends to ``allowed_signers`` (a control file, human-only)."""
    return f"{ANCHOR}{json.dumps(private_key_path)}\n" if private_key_path else ""


def forged_signing(human: dict[str, Any] | None, managed: dict[str, Any], folder: Path) -> str:
    """``FORGED`` if the signing values of the managed file are not what ``identity add`` wrote,
    else ``""``: the current and previous public keys must be in ``allowed_signers`` and
    ``private_key_path`` must be the line ``anchor_line`` wrote. A table that ``config.toml``
    sets is the human's and is not checked."""
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
