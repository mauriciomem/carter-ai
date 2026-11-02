"""What GitHub says about the branch ``carter push`` is about to update (best effort).

Read with the read-only token when one is stored; every answer is advice for the human, so a
missing token, an unreachable API or an unexpected reply gives a *notice*, never a failure.
Notes are plain strings starting with ``warning:`` or ``notice:``; they hold rule names and
numbers, never tokens or URLs with credentials.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from carter import ghtoken

_GITHUB_URL = re.compile(
    r"(?:https://(?:[^@/\s]+@)?github\.com/"
    r"|ssh://(?:[^@/\s]+@)?github\.com(?::\d+)?/"
    r"|[^@/\s]+@github\.com:)"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?"
)
_RULES = {
    "required_signatures": "requires signed commits",
    "pull_request": "requires a pull request (a direct push will be rejected)",
    "non_fast_forward": "blocks non-fast-forward pushes",
    "required_status_checks": "requires status checks",
    "update": "restricts who can update it",
}


def github_slug(url: str) -> tuple[str, str] | None:
    """``(owner, repo)`` for an https, ssh or scp-style github.com URL, else ``None``."""
    match = _GITHUB_URL.fullmatch(url.strip())
    return (match.group(1), match.group(2)) if match else None


def _get(base: str, path: str, token: str) -> tuple[int, object]:
    reply = ghtoken.request(base, "GET", path, token)
    try:
        return reply.status, json.loads(reply.text) if reply.status == 200 else None
    except ValueError:
        return reply.status, None


def branch_notes(url: str, branch: str, base_dir: Path | None = None) -> list[str]:
    """Protection warnings for ``branch`` of the repository at ``url``."""
    slug = github_slug(url)
    if slug is None:
        return ["notice: branch protection not checked (origin is not on github.com)"]
    token = ghtoken.stored_token(base_dir)
    if token is None:
        return [
            "notice: branch protection not checked (no read-only token; `carter github-token set`)"
        ]
    try:
        base = ghtoken.api_base()
    except Exception:  # noqa: BLE001 - any refusal means "do not send the token there"
        return ["notice: branch protection not checked (GITHUB_API_URL is not acceptable)"]
    repo, ref = f"{slug[0]}/{slug[1]}", quote(branch, safe="")
    notes: list[str] = []
    status, rules = _get(base, f"/repos/{repo}/rules/branches/{ref}", token)
    if status != 200 or not isinstance(rules, list):
        return [f"notice: branch protection not checked (GitHub answered HTTP {status or '?'})"]
    types = sorted({r.get("type", "") for r in rules if isinstance(r, dict)})
    notes += [f"warning: {t}: the branch {_RULES[t]}" for t in types if t in _RULES]
    status, info = _get(base, f"/repos/{repo}/branches/{ref}", token)
    if isinstance(info, dict) and info.get("protected") is True:
        notes.append("warning: the branch is protected on GitHub")
    return notes or ["notice: GitHub reports no protection rules for this branch"]
