"""The read-only GitHub token: store it, check it (RFC-0007 App C.7; plan 003 step 16).

Pure logic for ``carter github-token set|check``: no click, no subprocess, no printing.
The token lives in ``~/.carter/secrets/gh-read.token`` (dir 0700, file 0600, written
atomically, no trailing newline) and is only ever sent in an ``Authorization`` header, to
``https`` or to loopback. No message ever contains more than the first 4 characters of a
value that was supplied.

``check`` classifies the write probe (``POST repos/{o}/{r}/git/refs`` with an all-zero sha) by
HTTP status and response text, never by an exit code. Strings are the ones recorded in spike 4
(2026-11-02) with a real fine-grained read-only token: 403 ``Resource not accessible by
personal access token`` means the token cannot write; 422 (or 201) means it can.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from carter.checkitems import Item
from carter.identity import ConfigError, load_identity
from carter.identity.errors import E_CONFIG, E_PAT_PERM, E_PAT_TYPE, IdentityError
from carter.identity.schema import Github
from carter.identity.writer import WriterError, write_config
from carter.install.paths import carter_config_path, token_path

PAT_PREFIX = "github_pat_"
_WRONG_TYPE_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_")
_PAT_RE = re.compile(r"github_pat_[A-Za-z0-9_]{20,255}")
_FULL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.][A-Za-z0-9_.-]*")
_EXPIRY_RE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC")
EXPIRY_HEADER = "Github-Authentication-Token-Expiration"
EXPIRY_WARN = timedelta(days=14)
DEFAULT_API = "https://api.github.com"
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
PROBE_REF = "refs/heads/carter-write-probe"
ZERO_SHA = "0" * 40
_NOT_ACCESSIBLE = "Resource not accessible"
_TIMEOUT = 10.0


def _euid() -> int:
    return os.geteuid()


# -- validating and storing ------------------------------------------------------------


def validate_token(raw: str) -> str:
    """Return the token (one trailing newline removed) or raise ``E-PAT-TYPE``.

    Only fine-grained ``github_pat_`` tokens are accepted. The error names a wrong *type*
    by its 4-character prefix and never quotes anything else of the value."""
    token = raw.removesuffix("\n").removesuffix("\r")
    if _PAT_RE.fullmatch(token):
        return token
    if token.startswith(_WRONG_TYPE_PREFIXES):
        found = f"it starts with `{token[:4]}`, a classic or app token"
    elif token.startswith(PAT_PREFIX):
        found = "the value is not a well-formed `github_pat_` token"
    else:
        found = "the value does not look like a GitHub token"
    raise IdentityError(
        E_PAT_TYPE,
        f"Only fine-grained `{PAT_PREFIX}` tokens are accepted ({found}).",
        "create one at github.com/settings/personal-access-tokens (read-only, selected repos)",
    )


def _in_repository(path: Path) -> bool:
    """Is ``path`` inside a git work tree (a ``.git`` directory or file above it)?"""
    return any((parent / ".git").exists() for parent in path.resolve().parents)


def _perm_error(detail: str) -> IdentityError:
    return IdentityError(E_PAT_PERM, detail=detail)


def location_problem(path: Path, *, creating: bool) -> str:
    """Why ``path`` may not hold the token ("" if fine). ``creating``: the file may be absent."""
    folder = path.parent
    if _in_repository(path):
        return f"{path.name} is inside a git repository; keep it under ~/.carter/secrets"
    if folder.is_symlink():
        return f"{folder.name} is a symlink"
    if folder.exists() and stat.S_IMODE(folder.stat().st_mode) != 0o700:
        return f"{folder.name} must be mode 0700 (chmod 700 {folder})"
    try:
        st = path.lstat()
    except FileNotFoundError:
        return "" if creating else f"{path.name} does not exist"
    if stat.S_ISLNK(st.st_mode):
        return f"{path.name} is a symlink"
    if not stat.S_ISREG(st.st_mode):
        return f"{path.name} is not a regular file"
    if st.st_uid != _euid():
        return f"{path.name} is not owned by you"
    if stat.S_IMODE(st.st_mode) != 0o600:
        return f"{path.name} must be mode 0600 (chmod 600 {path})"
    return ""


@dataclass(frozen=True)
class Stored:
    path: Path
    recorded: bool  # [github] read_token_file was written to config.toml
    note: str = ""


def _write_private(path: Path, text: str) -> None:
    """Atomic write: temp file in the same 0700 directory, fsync, rename. Umask 077 throughout."""
    old = os.umask(0o077)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".gh-read.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="ascii", newline="") as fh:
                os.fchmod(fh.fileno(), 0o600)
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    finally:
        os.umask(old)


def _record(path: Path, base_dir: Path | None) -> tuple[bool, str]:
    """Put ``[github] read_token_file`` into config.toml; (recorded, why not)."""
    cfg_path = carter_config_path(base_dir)
    try:
        current = load_identity(cfg_path)
        github = Github(read_token_file=str(path))
        write_config(replace(current, github=github, state="current"), cfg_path)
    except (ConfigError, WriterError, OSError):
        return (
            False,
            "config.toml was left unchanged (unreadable or has keys Carter does not model)",
        )
    return True, ""


def store_token(raw: str, base_dir: Path | None = None) -> Stored:
    """Validate ``raw`` and write it to ``gh-read.token``. Nothing is written on any refusal."""
    token = validate_token(raw)
    path = token_path(base_dir)
    if problem := location_problem(path, creating=True):
        raise _perm_error(problem)
    _write_private(path, token)
    recorded, note = _record(path, base_dir)
    return Stored(path, recorded, note)


# -- talking to GitHub ------------------------------------------------------------------


def api_base() -> str:
    """``$GITHUB_API_URL`` or api.github.com. Plain http is only accepted for loopback, so the
    token can never cross the network unencrypted."""
    url = os.environ.get("GITHUB_API_URL", DEFAULT_API).rstrip("/")
    parts = urlparse(url)
    if parts.scheme == "https" and parts.hostname:
        return url
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return url
    raise IdentityError(
        E_CONFIG,
        "GITHUB_API_URL must be https (or http on loopback); refusing to send the token there.",
        f"scheme={parts.scheme or '?'} host={parts.hostname or '?'}",
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None  # a redirect would carry the Authorization header to another host


@dataclass(frozen=True)
class Reply:
    status: int  # 0: GitHub could not be reached
    text: str
    headers: dict[str, str]


def request(
    base: str, method: str, path: str, token: str, body: dict[str, str] | None = None
) -> Reply:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)  # noqa: S310
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "carter-github-token-check")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
    if urlparse(base).hostname in _LOOPBACK:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=_TIMEOUT) as resp:
            return Reply(resp.status, resp.read().decode("utf-8", "replace"), _lower(resp.headers))
    except urllib.error.HTTPError as exc:
        with contextlib.closing(exc):
            return Reply(exc.code, exc.read().decode("utf-8", "replace"), _lower(exc.headers))
    except (urllib.error.URLError, OSError, ValueError):
        return Reply(0, "", {})


def stored_token(base_dir: Path | None = None) -> str | None:
    """The stored token if the file passes every check (mode, owner, no link, outside a repo,
    a ``github_pat_`` value), else ``None``. Callers decide what to say; this never explains."""
    return _file_items(token_path(base_dir), required=False)[1]


def _lower(headers: object) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}  # type: ignore[attr-defined]


def parse_expiry(header: str) -> datetime | None:
    """``Github-Authentication-Token-Expiration``: ``YYYY-MM-DD HH:MM:SS UTC``."""
    text = header.strip()
    if not _EXPIRY_RE.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    except ValueError:
        return None


def classify_probe(status: int, text: str) -> str:
    """``read-only`` (403 "Resource not accessible"), ``writable`` (422 or 201) or ``unprobed``."""
    if status in (201, 422):
        return "writable"
    if status == 403 and _NOT_ACCESSIBLE in text:
        return "read-only"
    return "unprobed"


# -- check ------------------------------------------------------------------------------


def _expiry_item(header: str | None, now: datetime) -> Item:
    if header is None:
        return Item("info", "expiry", "no expiry header (the token may not expire)")
    expires = parse_expiry(header)
    if expires is None:
        return Item("warn", "expiry", "cannot read the expiry header; check the token on GitHub")
    left = expires - now
    day = expires.strftime("%Y-%m-%d")
    if left < timedelta(0):
        return Item(
            "red",
            "expiry",
            f"token expired on {day}",
            "create a new one and run `carter github-token set`",
        )
    text = f"expires {day} (in {left.days} days)"
    if left <= EXPIRY_WARN:
        return Item("warn", "expiry", text, "create a new token and run `carter github-token set`")
    return Item("ok", "expiry", text)


def _valid_repo(name: object) -> bool:
    """``owner/name`` with GitHub's character sets, and no ``.``/``..`` segment (the value
    ends up in a URL path)."""
    if not isinstance(name, str) or not _FULL_NAME_RE.fullmatch(name):
        return False
    return not any(part in (".", "..") for part in name.split("/"))


def _owned_repo(base: str, token: str, login: str) -> tuple[str | None, Item | None]:
    """A repository owned by ``login`` that the token can see: ``(full name, None)``, or
    ``(None, the item that explains why there is none)``. Repositories of other owners (an
    organisation the token merely reads) are never considered."""
    path = "/user/repos?affiliation=owner&sort=updated&per_page=30"
    reply = request(base, "GET", path, token)
    if reply.status != 200:
        text = f"unprobed: cannot list repositories (HTTP {reply.status})"
        return None, Item("warn", "write probe", text)
    try:
        listing = json.loads(reply.text)
    except ValueError:
        listing = None
    for entry in listing if isinstance(listing, list) else []:
        owner = entry.get("owner") if isinstance(entry, dict) else None
        name = entry.get("full_name") if isinstance(entry, dict) else None
        if (
            isinstance(owner, dict)
            and isinstance(owner.get("login"), str)
            and owner["login"].lower() == login.lower()
            and _valid_repo(name)
        ):
            return str(name), None
    text = (
        "skipped: no repository owned by the token's user is visible to it, so no write was "
        'attempted; set `[github] probe_repo = "owner/name"` in config.toml to choose one'
    )
    return None, Item("info", "write probe", text)


def _configured_probe_repo(base_dir: Path | None) -> tuple[str, list[Item]]:
    """``[github] probe_repo`` if set and well formed (a malformed one is ignored with an info)."""
    try:
        value = load_identity(carter_config_path(base_dir)).github.probe_repo
    except (ConfigError, OSError):
        return "", []
    if not value:
        return "", []
    if _valid_repo(value):
        return value, []
    text = "ignored: [github] probe_repo is not owner/name; using a repository you own instead"
    return "", [Item("info", "write probe", text)]


def _probe(base: str, token: str, login: str, base_dir: Path | None) -> list[Item]:
    """The one write attempt. It never prints the repository's name or owner."""
    configured, notes = _configured_probe_repo(base_dir)
    repo, skipped = (configured, None) if configured else _owned_repo(base, token, login)
    if repo is None:
        return [*notes, skipped] if skipped else notes
    which = "the configured probe repository" if configured else "a repository you own"
    body = {"ref": PROBE_REF, "sha": ZERO_SHA}
    reply = request(base, "POST", f"/repos/{repo}/git/refs", token, body)
    verdict = classify_probe(reply.status, reply.text)
    if verdict == "read-only":
        item = Item(
            "ok", "write probe", f"GitHub refused a write to {which}: the token is read-only"
        )
    elif verdict == "writable":
        fix = (
            "revoke it and create a token with Contents: read and Pull requests: write, "
            "then run `carter github-token set`"
        )
        item = Item(
            "red", "write probe", f"token is WRITABLE on {which} (HTTP {reply.status})", fix
        )
    else:
        text = f"unprobed: unexpected answer for {which} (HTTP {reply.status})"
        item = Item("warn", "write probe", text)
    if verdict == "writable":
        return [*notes, item]
    return [*notes, item, _pull_request_item(base, token, repo)]


def _pull_request_item(base: str, token: str, repo: str) -> Item:
    """The PR probe (D72): ``POST /pulls`` with an empty body can never create anything. GitHub
    validates the permission first: 422 = the token may open PRs, 403 = it may not."""
    reply = request(base, "POST", f"/repos/{repo}/pulls", token, {})
    if reply.status in (201, 422):
        return Item(
            "ok", "pull requests", "agents can open PRs (the token holds Pull requests: write)"
        )
    if reply.status == 403 and _NOT_ACCESSIBLE in reply.text:
        return Item(
            "warn",
            "pull requests",
            "agents can't open PRs",
            'add "Pull requests: write" to the token (Contents stays read)',
        )
    return Item("info", "pull requests", f"unprobed: unexpected answer (HTTP {reply.status})")


def _file_items(path: Path, required: bool) -> tuple[list[Item], str | None]:
    """The static checks. Returns the items and the token (``None`` if checking must stop)."""
    if not path.is_symlink() and not path.exists():
        how = "run `carter github-token set` in your own terminal"
        if required:
            return [Item("red", "file", f"no token file; {how}")], None
        return [Item("warn", "file", f"not provisioned ({how})")], None
    if problem := location_problem(path, creating=False):
        return [Item("red", "file", f"{E_PAT_PERM}: {problem}")], None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="ascii", errors="replace") as fh:
            raw = fh.read(4096)
    except OSError:
        return [Item("red", "file", f"{E_PAT_PERM}: cannot read {path.name}")], None
    try:
        token = validate_token(raw)
    except IdentityError as exc:
        return [Item("red", "type", f"{E_PAT_TYPE}: {exc}")], None
    return [Item("ok", "file", f"{path} (0600, yours, outside any repository)")], token


def _login(me: Reply) -> str:
    try:
        login = json.loads(me.text).get("login")
    except (ValueError, AttributeError):
        return ""
    return login if isinstance(login, str) else ""


def check_token(
    base_dir: Path | None = None, *, now: datetime | None = None, required: bool = True
) -> list[Item]:
    """Every check on the stored token, as items. Makes three requests at most: ``GET /user``,
    ``GET /user/repos`` and the one write probe GitHub must refuse (on a repository the token's
    user owns, or ``[github] probe_repo``; its name is never printed)."""
    now = now or datetime.now(UTC)
    items, token = _file_items(token_path(base_dir), required)
    if token is None:
        return items
    try:
        base = api_base()
    except IdentityError as exc:
        return [*items, Item("red", "endpoint", str(exc), exc.detail)]
    me = request(base, "GET", "/user", token)
    if me.status == 0:
        return [*items, Item("red", "github", "could not reach GitHub; no network check was made")]
    if me.status != 200:
        text = "GitHub rejected the token (HTTP 401): expired, revoked or mistyped"
        if me.status != 401:
            text = f"GitHub answered HTTP {me.status} to GET /user"
        return [
            *items,
            Item("red", "github", text, "run `carter github-token set` with a new token"),
        ]
    if "x-oauth-scopes" in me.headers:
        return [
            *items,
            Item(
                "red",
                "type",
                f"{E_PAT_TYPE}: GitHub reports OAuth scopes, so this is a classic token",
            ),
        ]
    items.append(Item("ok", "type", f"`{PAT_PREFIX}` fine-grained token accepted by GitHub"))
    items.append(_expiry_item(me.headers.get(EXPIRY_HEADER.lower()), now))
    login = _login(me)
    items += _probe(base, token, login, base_dir)
    items.append(
        Item(
            "info",
            "repository selection",
            "Prefer selecting only the repositories Carter works on; 'All repositories' lets "
            "agents read every repo the token covers (accepted, but wider than needed). GitHub "
            "does not show the selection to the token, so Carter cannot check it",
        )
    )
    return items
