"""Which GitHub repository an ``origin`` URL names (D68 f dropped the branch-protection notice)."""

from __future__ import annotations

import re

_GITHUB_URL = re.compile(
    r"(?:https://(?:[^@/\s]+@)?github\.com/"
    r"|ssh://(?:[^@/\s]+@)?github\.com(?::\d+)?/"
    r"|[^@/\s]+@github\.com:)"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?"
)


def github_slug(url: str) -> tuple[str, str] | None:
    """``(owner, repo)`` for an https, ssh or scp-style github.com URL, else ``None``."""
    match = _GITHUB_URL.fullmatch(url.strip())
    return (match.group(1), match.group(2)) if match else None
