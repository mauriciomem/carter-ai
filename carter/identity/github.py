"""The calls of the unauthenticated GitHub client (freeze H13; plan 005 step 14).

Used by ``identity add``, ``identity verify --remote`` and ``check --host``: ``get_user``,
``get_signing_keys`` (2 pages of 100 at most), ``get_auth_keys`` (the ``<login>.keys`` page) and
``get_commit_verification``. Logins and repository names are validated before they go into a URL.
Transport, base URLs, limits and errors: ``github_http``.

Stdlib-only (see ``test_stdlib_only``).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass

from carter.identity.github_http import (
    CALL_BUDGET,
    DEFAULT_API,
    DEFAULT_WEB,
    MAX_BYTES,
    GitHubError,
    api_base,
    fetch,
    get_json,
    web_base,
)

__all__ = ["DEFAULT_API", "DEFAULT_WEB", "MAX_BYTES", "GitHubError", "SigningKey", "User",
           "Verification", "api_base", "blob_of", "get_auth_keys", "get_commit_verification",
           "get_signing_keys", "get_user", "web_base"]  # fmt: skip
PAGE_SIZE, MAX_PAGES = 100, 2
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REPO_PART = re.compile(r"[A-Za-z0-9._-]{1,100}")
SHA = re.compile(r"[0-9a-fA-F]{7,40}")


@dataclass(frozen=True)
class User:
    login: str
    id: int


@dataclass(frozen=True)
class SigningKey:
    id: int
    blob: str  # "type base64", comment dropped
    title: str  # display only; may be empty


@dataclass(frozen=True)
class Verification:
    verified: bool
    reason: str


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _login(value: str) -> str:
    if not LOGIN.fullmatch(value):
        raise ValueError("not a valid GitHub login")
    return value


def blob_of(line: str) -> str:
    """``"type base64"`` from a key line (comment dropped), ``""`` if it has fewer than 2 tokens."""
    parts = line.split()
    return f"{parts[0]} {parts[1]}" if len(parts) >= 2 else ""


def get_user(login: str, env: Mapping[str, str] | None = None) -> User:
    """The account's id and canonical login; an Organization or a Bot is ``not-a-user``."""
    deadline = time.monotonic() + CALL_BUDGET
    doc = get_json(f"{api_base(env)}/users/{_login(login)}", deadline)
    if not (isinstance(doc, dict) and _int(doc.get("id"))):
        raise GitHubError("bad-response", "GitHub's user record has an unexpected shape")
    if not (isinstance(doc.get("login"), str) and isinstance(doc.get("type"), str)):
        raise GitHubError("bad-response", "GitHub's user record has an unexpected shape")
    if doc["type"] != "User" or doc["id"] <= 0:
        raise GitHubError("not-a-user", f"the account is a {doc['type']}, not a User")
    return User(doc["login"], doc["id"])


def get_signing_keys(login: str, env: Mapping[str, str] | None = None) -> list[SigningKey]:
    """The account's SSH *signing* keys (up to 2 pages of 100). ``title`` is display only."""
    deadline = time.monotonic() + CALL_BUDGET
    base, out = api_base(env), []
    for page in range(1, MAX_PAGES + 1):
        url = f"{base}/users/{_login(login)}/ssh_signing_keys?per_page={PAGE_SIZE}&page={page}"
        items = get_json(url, deadline)
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise GitHubError("bad-response", "GitHub's signing key list has an unexpected shape")
        for item in items:
            blob = blob_of(item["key"]) if isinstance(item.get("key"), str) else ""
            ident = item.get("id")
            if not blob or not _int(ident):
                raise GitHubError("bad-response", "a signing key record has an unexpected shape")
            title = item.get("title")
            out.append(SigningKey(int(ident), blob, title if isinstance(title, str) else ""))
        if len(items) < PAGE_SIZE:
            break
    return out


def get_auth_keys(login: str, env: Mapping[str, str] | None = None) -> list[str]:
    """The account's *authentication* keys from ``/<login>.keys`` (plain text, ``type blob``)."""
    deadline = time.monotonic() + CALL_BUDGET
    url = f"{web_base(api_base(env))}/{_login(login)}.keys"
    text = fetch(url, "text/plain", ("text/plain",), deadline)
    return [b for line in text.splitlines() if (b := blob_of(line))]


def get_commit_verification(
    owner: str, repo: str, sha: str, env: Mapping[str, str] | None = None
) -> Verification:
    """GitHub's verdict on one commit's signature (``commit.verification``)."""
    if not (REPO_PART.fullmatch(owner) and REPO_PART.fullmatch(repo) and SHA.fullmatch(sha)):
        raise ValueError("owner, repository or commit id is not valid")
    deadline = time.monotonic() + CALL_BUDGET
    doc = get_json(f"{api_base(env)}/repos/{owner}/{repo}/commits/{sha}", deadline)
    commit = doc.get("commit") if isinstance(doc, dict) else None
    ver = commit.get("verification") if isinstance(commit, dict) else None
    if not (isinstance(ver, dict) and isinstance(ver.get("verified"), bool)):
        raise GitHubError("bad-response", "the commit record has no verification object")
    reason = ver.get("reason")
    return Verification(ver["verified"], reason if isinstance(reason, str) else "")
