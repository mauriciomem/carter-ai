"""A loopback stand-in for api.github.com .

Scripted routes, a log of every request (method, path, headers, body) and a list of
requests nobody scripted, so a test can prove exactly what was sent. The response bodies in
``SPIKE_*`` are the strings recorded from a real read-only fine-grained PAT,
2026-11-02), with the repository placeholder ``<o>/<r>``. Never talks to the network.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FIXTURES = Path(__file__).resolve().parent / "data" / "github"
DEFAULT_API = "https://api.github.com"
DEFAULT_WEB = "https://github.com"

ZERO_SHA = "0" * 40
EXPIRY_HEADER = "Github-Authentication-Token-Expiration"

SPIKE_403 = json.dumps(
    {
        "message": "Resource not accessible by personal access token",
        "documentation_url": "https://docs.github.com/rest/git/refs#create-a-reference",
        "status": "403",
    }
)
SPIKE_422 = json.dumps(
    {
        "message": "Object does not exist",
        "documentation_url": "https://docs.github.com/rest/git/refs#create-a-reference",
        "status": "422",
    }
)
SPIKE_401 = json.dumps({"message": "Bad credentials", "status": "401"})
SPIKE_404 = json.dumps({"message": "Not Found", "status": "404"})


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Reply:
    status: int = 200
    body: str = "{}"
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = "application/json; charset=utf-8"


def fixture(name: str) -> str:
    """The text of ``tests/data/github/<name>`` (shapes pinned from the public REST docs)."""
    return (FIXTURES / name).read_text()


def web_base(api_url: str | None) -> str:
    """The origin that serves ``/<login>.keys`` for a given ``GITHUB_API_URL``.

    Default API: ``https://github.com``. A GitHub Enterprise Server API root ends in
    ``/api/v3``: its origin. Anything else (a loopback fake): the same URL, so one server
    covers both the API and the web page. Redirects are never followed.
    """
    url = (api_url or DEFAULT_API).rstrip("/")
    if url == DEFAULT_API:
        return DEFAULT_WEB
    if urlsplit(url).path == "/api/v3":
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"
    return url


RATE_HEADERS = {
    "x-ratelimit-limit": "60",
    "x-ratelimit-remaining": "0",
    "x-ratelimit-used": "60",
    "x-ratelimit-reset": "1793760000",
    "x-ratelimit-resource": "core",
}


class FakeGitHub:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Reply | Callable[[Recorded], Reply]] = {}
        self.requests: list[Recorded] = []
        self.unexpected: list[Recorded] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                rec = Recorded(
                    self.command,
                    self.path,
                    {k.lower(): v for k, v in self.headers.items()},
                    self.rfile.read(length) if length else b"",
                )
                outer.requests.append(rec)
                route = outer.routes.get((rec.method, rec.path.split("?")[0]))
                if route is None:
                    outer.unexpected.append(rec)
                    reply = Reply(599, "unscripted")
                else:
                    reply = route(rec) if callable(route) else route
                payload = reply.body.encode()
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.content_type)
                self.send_header("Content-Length", str(len(payload)))
                for key, value in reply.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve  # noqa: N815

            def log_message(self, *args: object) -> None:  # silence
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self) -> FakeGitHub:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    # -- scripting helpers ---------------------------------------------------------
    def authorized_requests(self) -> list[Recorded]:
        """Requests that carried credentials (the unauthenticated calls must have none)."""
        return [r for r in self.requests if "authorization" in r.headers or "cookie" in r.headers]

    def public_world(
        self,
        login: str = "octocat",
        *,
        user: str = "user.json",
        signing_keys: str = "signing-keys-match.json",
        auth_keys: str = "keys-without.txt",
    ) -> None:
        """The three unauthenticated reads of ``identity add``: the account, its signing
        keys (API) and its authentication keys (the web page, same server)."""
        self.on("GET", f"/users/{login}", Reply(200, fixture(user)))
        self.on("GET", f"/users/{login}/ssh_signing_keys", Reply(200, fixture(signing_keys)))
        self.on(
            "GET",
            f"/{login}.keys",
            Reply(200, fixture(auth_keys), content_type="text/plain; charset=utf-8"),
        )

    def commit_world(self, owner_repo: str, sha: str, name: str = "commit-verified.json") -> None:
        self.on("GET", f"/repos/{owner_repo}/commits/{sha}", Reply(200, fixture(name)))

    def on(self, method: str, path: str, reply: Reply | Callable[[Recorded], Reply]) -> None:
        self.routes[(method, path)] = reply

    def readonly_token_world(
        self,
        owner_repo: str = "carter-llm/zz-probe-repo",
        *,
        expiry: str | None = None,
        pulls: int = 422,
    ) -> None:
        """What a read-only fine-grained PAT sees: GET /user and /user/repos work, writes 403.

        ``owner_repo`` is a repository the token's user owns (the owner is the login of
        ``GET /user``), so the default name is distinctive: tests grep output for it."""
        owner = owner_repo.split("/")[0]
        headers = {"X-Accepted-Github-Permissions": "allows_permissionless_access=true"}
        if expiry:
            headers[EXPIRY_HEADER] = expiry
        self.on("GET", "/user", Reply(200, json.dumps({"login": owner}), headers))
        listing = [{"full_name": owner_repo, "owner": {"login": owner}}]
        self.on("GET", "/user/repos", Reply(200, json.dumps(listing)))
        self.on("POST", f"/repos/{owner_repo}/git/refs", Reply(403, SPIKE_403))
        # the token may hold `Pull requests: write`; an empty POST then fails validation (422)
        # and creates nothing, otherwise GitHub says 403 "Resource not accessible"
        self.on(
            "POST",
            f"/repos/{owner_repo}/pulls",
            Reply(pulls, SPIKE_403 if pulls == 403 else SPIKE_422),
        )
