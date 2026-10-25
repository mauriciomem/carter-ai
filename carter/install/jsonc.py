"""JSONC parsing (JSON with Comments, as used by ``opencode.json`` and VS Code settings)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from carter.install.console import log_debug


def _strip_jsonc(text: str) -> str:
    """Strip // and /* */ comments and trailing commas from JSONC text.

    Handles comments inside strings correctly (leaves them alone).
    """
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

    # Remove trailing commas before } or ]
    return re.sub(r",\s*([}\]])", r"\1", "".join(result))


def _load_jsonc(path: Path) -> dict | None:
    """Load a JSONC file (JSON with Comments). Returns None on failure."""
    try:
        raw = path.read_text()
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
    path.write_text(json.dumps(data, indent=2) + "\n")
