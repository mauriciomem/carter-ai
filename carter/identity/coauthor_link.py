"""GitHub linking of the human's co-author email, and its cache.

Split from ``coauthor`` for size; everything here is re-exported there. Stdlib-only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from carter.identity.rules import is_agent

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

# In role author the trailer is the human's only GitHub credit, so an email GitHub cannot map to an
# account is worth a warning. ``yes(noreply)``: the id+login address, confirmed by the public
# ``GET /users/<login>`` (the unauthenticated client); ``yes(verified)``: a verified email of
# the human's own account, asked of ``gh api /user/emails`` -- only in a human terminal, because
# ``gh`` there holds the human's token. The answer is cached as a hash, so ``--emit`` and the
# plugin path never touch the network or ``gh``.

LINK_CACHE_REL = ".carter/run/coauthor-link.json"
LINK_CACHE_TTL_S = 7 * 24 * 3600
LINK_STATES = ("noreply", "verified")
_NOREPLY = re.compile(r"(\d+)\+([a-z0-9][a-z0-9_-]*)@users\.noreply\.github\.com")

GetUser = Callable[[str], object]  # login -> an object with .id and .login; raises on any failure
ListEmails = Callable[[], "list[dict] | None"]  # `gh api /user/emails`; None when unavailable


def cache_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / LINK_CACHE_REL


def email_key(email: str) -> str:
    """The cache key: the hash of the casefolded email. The email itself is never stored."""
    return hashlib.sha256(email.casefold().encode("utf-8")).hexdigest()


def noreply_parts(email: str) -> tuple[int, str] | None:
    """``(id, login)`` of an ``<id>+<login>@users.noreply.github.com`` address, else ``None``."""
    match = _NOREPLY.fullmatch(email.casefold())
    return (int(match.group(1)), match.group(2)) if match else None


def cached_link(email: str, home: Path | None = None, now: float | None = None) -> str:
    """The fresh cached state for ``email`` (``"noreply"`` / ``"verified"``), else ``""``.

    Reads one small file; an unreadable, malformed, expired or foreign entry is just ``""``."""
    try:
        data = json.loads(cache_path(home).read_text(encoding="utf-8"))
        row = data[email_key(email)]
        state, at = row["linked"], float(row["at"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""
    fresh = 0 <= (time.time() if now is None else now) - at <= LINK_CACHE_TTL_S
    return state if state in LINK_STATES and fresh else ""


def record_link(email: str, state: str, home: Path | None = None, now: float | None = None) -> None:
    """Write ``state`` for ``email`` (0600, atomic, expired rows dropped). Human terminal only:
    callers go through ``refresh_link``, which checks."""
    if state not in LINK_STATES:
        raise ValueError(f"not a link state: {state!r}")
    path, stamp = cache_path(home), time.time() if now is None else now
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        rows = {k: v for k, v in rows.items() if stamp - float(v["at"]) <= LINK_CACHE_TTL_S}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        rows = {}
    rows[email_key(email)] = {"linked": state, "at": stamp}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".coauthor-link.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def check_link(email: str, get_user: GetUser, list_emails: ListEmails) -> str:
    """``"noreply"`` / ``"verified"`` / ``""`` (unknown). Network and ``gh`` happen here only."""
    parts = noreply_parts(email)
    if parts is not None:
        uid, login = parts
        try:
            user = get_user(login)
            if (
                getattr(user, "id", None) == uid
                and str(getattr(user, "login", "")).casefold() == login
            ):
                return "noreply"
        except Exception:  # noqa: BLE001 - offline or rate-limited is "not known", never a failure
            pass
    try:
        rows = list_emails()
    except Exception:  # noqa: BLE001
        rows = None
    for row in rows or []:
        if (
            isinstance(row, dict)
            and row.get("verified") is True
            and str(row.get("email", "")).casefold() == email.casefold()
        ):
            return "verified"
    return ""


def refresh_link(
    email: str,
    get_user: GetUser,
    list_emails: ListEmails,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    *,
    record: bool = True,
) -> str:
    """The link state for ``email``, asking GitHub and ``gh`` and caching a positive answer
    (unless ``record`` is false: a dry run writes nothing) -- but only in a human terminal. In an
    agent shell it returns what the cache holds and does nothing else (``gh`` there would be the
    human's token; the cache is the human's file)."""
    if is_agent(os.environ if env is None else env):
        return cached_link(email, home)
    state = check_link(email, get_user, list_emails)
    if state and record:
        with contextlib.suppress(OSError):  # an unwritable cache must not fail `identity add`
            record_link(email, state, home)
    return state


def gh_user_emails(
    run: Runner | None = None, env: Mapping[str, str] | None = None
) -> list[dict] | None:
    """``gh api /user/emails`` parsed, or ``None`` (no gh, not logged in, no scope, bad JSON)."""
    runner = run or subprocess.run
    try:
        done = runner(
            ["gh", "api", "/user/emails"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=15,
            env=None if env is None else dict(env),
            check=False,
        )
        rows = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return rows if isinstance(rows, list) else None
