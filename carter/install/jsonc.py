"""JSONC parsing (JSON with Comments, as used by ``opencode.jsonc``)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from carter.install.console import log_debug


def _strip_jsonc(text: str) -> str:
    """Strip // and /* */ comments and trailing commas from JSONC text.

    Handles comments inside strings correctly (leaves them alone).
    """
    # Remove trailing commas before } or ]
    return re.sub(r",\s*([}\]])", r"\1", _strip_comments(text))


def has_comments(text: str) -> bool:
    """True when ``text`` contains a // or /* */ comment outside strings."""
    return _strip_comments(text) != text


def _strip_comments(text: str) -> str:
    """Strip // and /* */ comments outside string literals."""
    result: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        # String literal — copy verbatim, including any // or /* inside
        if c == '"':
            result.append(c)
            i += 1
            while i < n:
                sc = text[i]
                result.append(sc)
                if sc == "\\" and i + 1 < n:
                    i += 1
                    result.append(text[i])
                elif sc == '"':
                    break
                i += 1
            i += 1
            continue

        # Single-line comment
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            # Skip to end of line
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue

        # Block comment
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2  # skip */
            continue

        result.append(c)
        i += 1

    return "".join(result)


def _load_jsonc(path: Path) -> dict | None:
    """Load a JSONC file (JSON with Comments). Returns None on failure."""
    try:
        raw = path.read_text(encoding="utf-8")
        stripped = _strip_jsonc(raw)
        return json.loads(stripped)
    except (json.JSONDecodeError, OSError) as e:
        log_debug(f"JSONC parse failed for {path}: {e}")
        return None


def _write_json(path: Path, data: dict) -> None:
    """Write ``data`` as 2-space-indented JSON.

    Comments and trailing commas of a JSONC original are not preserved.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_json_atomic(path: Path, data: dict) -> Path:
    """Like ``_write_json`` but atomic and symlink-preserving (the live OpenCode config).

    Writes onto ``realpath`` so a dotfile-managed link stays a link, keeps an existing
    file's permission bits, and leaves the old file intact if anything fails."""
    from carter.install.atomic import atomic_write_bytes

    return atomic_write_bytes(
        path, (json.dumps(data, indent=2) + "\n").encode(), follow_symlinks=True
    )
