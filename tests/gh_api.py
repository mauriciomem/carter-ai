"""A loopback stand-in for api.github.com (plan 003 steps 16, 19, 21).

Scripted routes, a log of every request (method, path, headers, body) and a list of
requests nobody scripted, so a test can prove exactly what was sent. The response bodies in
``SPIKE_*`` are the strings recorded from a real read-only fine-grained PAT (spike 4,
2026-11-02), with the repository placeholder ``<o>/<r>``. Never talks to the network.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
                self.send_header("Content-Type", "application/json")
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
    def on(self, method: str, path: str, reply: Reply | Callable[[Recorded], Reply]) -> None:
        self.routes[(method, path)] = reply

    def readonly_token_world(
        self, owner_repo: str = "carter-llm/zz-probe-repo", *, expiry: str | None = None
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
