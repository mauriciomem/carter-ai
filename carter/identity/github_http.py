"""HTTP transport of the unauthenticated GitHub client.

Never sends credentials (no ``Authorization``, no cookies, no token from the environment or a
file). ``$GITHUB_API_URL`` is honoured: https anywhere, plain http only on loopback, nothing else
and no credentials in the URL (``E-CONFIG``). Redirects are never followed, proxies are bypassed
for loopback, timeouts are 10 s per request and 20 s per call, a response is at most 1 MiB and
its content type is checked. Failures are typed (``GitHubError.kind``) with a one-line status of
at most 200 characters, never a response body. Nothing is logged.

Stdlib-only (see ``test_stdlib_only``).
"""

from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from carter.identity.errors import E_CONFIG, MSG_CONFIG, IdentityError

DEFAULT_API = "https://api.github.com"
DEFAULT_WEB = "https://github.com"
MAX_BYTES = 1024 * 1024
REQUEST_TIMEOUT = 10.0
CALL_BUDGET = 20.0


class GitHubError(Exception):
    """A typed failure. ``kind``: ``not-found``, ``not-a-user``, ``rate-limit``, ``server``,
    ``bad-response``, ``network``. ``str(error)`` is a one-line status of at most 200 characters."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message[:200])
        self.kind = kind


def _loopback(host: str | None) -> bool:
    if host is None or host == "localhost":
        return host == "localhost"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def api_base(env: Mapping[str, str] | None = None) -> str:
    """``$GITHUB_API_URL`` or the default; ``E-CONFIG`` for an unsafe value."""
    url = (os.environ if env is None else env).get("GITHUB_API_URL", DEFAULT_API).rstrip("/")
    parts = urlsplit(url)
    ok = parts.scheme == "https" or (parts.scheme == "http" and _loopback(parts.hostname))
    if not ok or not parts.hostname or parts.username or parts.password or parts.query:
        raise IdentityError(
            E_CONFIG,
            MSG_CONFIG,
            "GITHUB_API_URL must be https (or http on loopback), no credentials",
        )
    return url


def web_base(api_url: str) -> str:
    """The origin that serves ``/<login>.keys`` for ``api_url``."""
    if api_url.rstrip("/") == DEFAULT_API:
        return DEFAULT_WEB
    parts = urlsplit(api_url)
    if parts.path.rstrip("/") == "/api/v3":
        return f"{parts.scheme}://{parts.netloc}"
    return api_url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _opener(url: str) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [_NoRedirect()]
    if _loopback(urlsplit(url).hostname):
        handlers.append(urllib.request.ProxyHandler({}))  # never through a proxy for loopback
    return urllib.request.build_opener(*handlers)


def fetch(url: str, accept: str, content_types: tuple[str, ...], deadline: float) -> str:
    request = urllib.request.Request(
        url, headers={"Accept": accept, "User-Agent": "carter-identity"}
    )
    left = min(REQUEST_TIMEOUT, deadline - time.monotonic())
    if left <= 0:
        raise GitHubError("network", "GitHub did not answer within the time budget")
    try:
        with _opener(url).open(request, timeout=left) as resp:
            kind = (resp.headers.get_content_type() or "").lower()
            body = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise http_error(exc) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        raise GitHubError("network", f"could not reach GitHub ({type(reason).__name__})") from None
    if len(body) > MAX_BYTES:
        raise GitHubError("bad-response", "GitHub's answer is larger than 1 MiB; refusing it")
    if kind not in content_types:
        raise GitHubError("bad-response", f"unexpected content type {kind[:60]!r}")
    return body.decode("utf-8", "replace")


def http_error(exc: urllib.error.HTTPError) -> GitHubError:
    code = exc.code
    if code in (301, 302, 303, 307, 308):
        return GitHubError(
            "bad-response", f"GitHub answered HTTP {code} (redirects are not followed)"
        )
    if code == 404:
        return GitHubError("not-found", "GitHub answered HTTP 404 (not found)")
    if code in (403, 429):
        reset = exc.headers.get("x-ratelimit-reset", "")
        when = ""
        if reset.isdigit():
            when = f"; resets at {datetime.fromtimestamp(int(reset), UTC):%Y-%m-%d %H:%M:%SZ}"
        text = f"GitHub refused the request (HTTP {code}), probably a rate limit{when}"
        return GitHubError("rate-limit", text)
    if code >= 500:
        return GitHubError("server", f"GitHub answered HTTP {code}")
    return GitHubError("bad-response", f"GitHub answered HTTP {code}")


def get_json(url: str, deadline: float) -> Any:
    text = fetch(url, "application/vnd.github+json", ("application/json",), deadline)
    try:
        return json.loads(text)
    except ValueError:
        raise GitHubError("bad-response", "GitHub's answer is not valid JSON") from None
