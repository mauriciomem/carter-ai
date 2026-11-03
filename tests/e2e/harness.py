"""Isolated OpenCode rig for the opt-in e2e suite (plan 004, step 2).

What it guarantees (plan 003 lessons, RFC-0007 App C.8 contract tests):

* The server and the mock model run with a **from-scratch environment**: own ``HOME`` and
  ``XDG_*`` under a short base directory, no ``SSH_AUTH_SOCK``, no tokens, no ``OPENCODE_*``
  or ``AGENT`` variables inherited from the agent shell that runs the tests.
* The real OpenCode service (its port, its ``service.json``) is never contacted: the rig starts
  its own ``opencode serve`` on its own port, and ``opencode service set port <free>`` runs in
  the isolated HOME before any ``debug`` call.
* The provider list is checked to be exactly ``[mock]`` before any prompt is sent. A broken
  config makes OpenCode fall back to its free-tier provider, so this is the gate.
* Optional: the whole rig runs inside ``unshare -rn`` (loopback only). When that is not
  available it falls back to plain loopback; the mock-only provider list is the main guard.
* Logs hold names and states only. The server password is random, lives in the process
  environment only and is scanned for in the logs at stop.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_BASE_LEN = 60  # bytes; macOS sun_path is 104 and sockets live below the base dir
MOCK_PROVIDER = "mock"
HERE = Path(__file__).resolve().parent
USER = "opencode"  # HTTP basic-auth user of `opencode serve`
READY_TIMEOUT = 40.0


class RigError(Exception):
    """The rig refuses to start or to continue (isolation could not be proven)."""


# --- pure helpers (unit tested) --------------------------------------------------------------


def free_port() -> int:
    """A currently free loopback TCP port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def check_base_dir(base: Path) -> Path:
    """The rig's base directory must be absolute and at most ``MAX_BASE_LEN`` bytes."""
    if not base.is_absolute():
        raise RigError(f"base dir is relative: {base}")
    if len(os.fsencode(base)) > MAX_BASE_LEN:
        raise RigError(f"base dir is longer than {MAX_BASE_LEN} bytes (macOS sun_path): {base}")
    return base


def refuse_real_home(path: Path, real_home: Path) -> None:
    """Raise when ``path`` is the developer's real home or lies inside it (symlinks resolved)."""
    resolved = path.resolve()
    real = real_home.resolve()
    if resolved == real or real in resolved.parents:
        raise RigError(f"refusing to use the real home or a path inside it: {path}")


def render_config(mock_port: int, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """OpenCode config with the mock as the only provider.

    ``extra`` may add keys (a plugin registration, agents, policies) but never a provider or a
    wider ``enabled_providers``: the mock-only guarantee is not negotiable.
    """
    cfg: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{MOCK_PROVIDER}/mock-1",
        "enabled_providers": [MOCK_PROVIDER],
        "providers": {
            MOCK_PROVIDER: {
                "name": "Mock",
                "env": ["MOCK_KEY"],
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": f"http://127.0.0.1:{mock_port}/v1", "apiKey": "x"},
                "models": {"mock-1": {"name": "Mock 1", "capabilities": {"tools": True}}},
            }
        },
    }
    for key, value in (extra or {}).items():
        if key in ("providers", "enabled_providers", "model"):
            raise RigError(f"extra config may not set {key}: the rig is mock-provider only")
        cfg[key] = value
    return cfg


def isolated_env(base: Path, *, bin_dir: str, password: str) -> dict[str, str]:
    """Environment for the server: built from scratch, nothing inherited."""
    home = base / "home"
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "PATH": f"{bin_dir}:/usr/local/bin:/usr/bin:/bin",
        "TERM": "xterm-256color",
        "LANG": "C.UTF-8",
        "OPENCODE_SERVER_PASSWORD": password,
    }


def env_names(env: Mapping[str, Any]) -> list[str]:
    """Variable names only, sorted. Logs never carry values."""
    return sorted(env)


def assert_only_mock(provider_ids: Iterable[str]) -> None:
    """The provider gate: exactly ``[mock]`` or the rig aborts before any prompt."""
    ids = list(provider_ids)
    if ids != [MOCK_PROVIDER]:
        raise RigError(f"providers are not exactly [{MOCK_PROVIDER}]: {ids}")


def secret_in_logs(logdir: Path, secret: str) -> bool:
    """True when ``secret`` appears in any file below ``logdir``."""
    needle = secret.encode()
    return any(needle in p.read_bytes() for p in logdir.rglob("*") if p.is_file())


def netns_available() -> bool:
    """Can this host run ``unshare -rn`` with ``ip``, ``nsenter`` and ``curl``?"""
    if sys.platform != "linux" or not all(
        shutil.which(t) for t in ("unshare", "ip", "nsenter", "curl")
    ):
        return False
    try:
        return (
            subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=10).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


# --- the rig ---------------------------------------------------------------------------------


@dataclass
class Rig:
    """A real OpenCode server in an isolated HOME with a scripted mock model.

    Use as a context manager. ``plugins`` maps a directory name to the source of an
    ``index.ts`` copied to ``~/.config/opencode/plugins/<name>/`` (registration form: step 3).
    ``extra_files`` maps a path relative to the isolated HOME to file content (other registration
    forms, broken plugins); ``ws_files`` is the same relative to the workspace (a project
    ``.opencode/``).
    ``__LOGS__`` in plugin sources and extra files is the log directory.
    """

    opencode: str
    base: Path
    real_home: Path
    use_netns: bool = False
    extra_config: Mapping[str, Any] = field(default_factory=dict)
    plugins: Mapping[str, str] = field(default_factory=dict)
    extra_files: Mapping[str, str] = field(default_factory=dict)
    ws_files: Mapping[str, str] = field(default_factory=dict)
    server_env_extra: Mapping[str, str] = field(default_factory=dict)
    port: int = 0
    mock_port: int = 0
    password: str = field(default_factory=lambda: secrets.token_hex(16), repr=False)
    _procs: list[subprocess.Popen[bytes]] = field(default_factory=list, repr=False)
    _ns: subprocess.Popen[bytes] | None = field(default=None, repr=False)

    # paths ---------------------------------------------------------------------------------

    @property
    def home(self) -> Path:
        return self.base / "home"

    @property
    def ws(self) -> Path:
        return self.base / "ws"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    @property
    def config_file(self) -> Path:
        return self.home / ".config/opencode/opencode.jsonc"

    def env(self) -> dict[str, str]:
        env = isolated_env(
            self.base, bin_dir=str(Path(self.opencode).parent), password=self.password
        )
        env.update(self.server_env_extra)
        return env

    # lifecycle -----------------------------------------------------------------------------

    def __enter__(self) -> Rig:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def prepare(self) -> None:
        check_base_dir(self.base)
        refuse_real_home(self.base, self.real_home)
        refuse_real_home(self.home, self.real_home)
        for d in (self.home, self.ws, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        self.base.chmod(0o700)
        self.port = self.port or free_port()
        self.mock_port = self.mock_port or free_port()
        (self.home / ".gitconfig").write_text(
            "[user]\n\tname = E2E Human\n\temail = e2e-human@example.invalid\n"
            "[init]\n\tdefaultBranch = main\n"
        )
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps(render_config(self.mock_port, extra=self.extra_config), indent=2)
        )
        for name, source in self.plugins.items():
            target = self.config_file.parent / "plugins" / name
            target.mkdir(parents=True, exist_ok=True)
            (target / "index.ts").write_text(source.replace("__LOGS__", str(self.logs)))
        for rel, content in self.extra_files.items():
            target = self.home / rel
            refuse_real_home(target, self.real_home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.replace("__LOGS__", str(self.logs)))
        for rel, content in self.ws_files.items():
            target = self.ws / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.replace("__LOGS__", str(self.logs)))
        if not (self.ws / ".git").exists():
            self._git(self.ws, "init", "-q")
            self._git(self.ws, "commit", "-q", "--allow-empty", "-m", "init")
        (self.logs / "rig.json").write_text(
            json.dumps(
                {
                    "env_names": env_names(self.env()),
                    "netns": self.use_netns,
                    "ports": [self.port, self.mock_port],
                }
            )
        )

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, env=self.env(), check=True, capture_output=True)

    def _wrap(self, argv: Sequence[str]) -> list[str]:
        if self._ns is None:
            return list(argv)
        return [
            "nsenter",
            "-t",
            str(self._ns.pid),
            "-U",
            "-n",
            "--preserve-credentials",
            "--",
            *argv,
        ]

    def _spawn(
        self, argv: Sequence[str], log: str, cwd: Path, env: Mapping[str, str]
    ) -> subprocess.Popen[bytes]:
        out = open(self.logs / log, "ab")  # noqa: SIM115 - handed to the child
        proc = subprocess.Popen(
            self._wrap(argv),
            cwd=cwd,
            env=dict(env),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        out.close()
        self._procs.append(proc)
        return proc

    def restart(self) -> None:
        """Stop and start again on the same HOME and ports, keeping every file as it is."""
        self.stop_service()  # a debug-spawned service would keep the old netns alive
        self.stop()
        self.start(fresh=False)

    def start(self, *, fresh: bool = True) -> None:
        if fresh:
            self.prepare()
        try:
            if self.use_netns:
                self._ns = subprocess.Popen(
                    ["unshare", "-rn", "sh", "-c", "ip link set lo up; exec sleep 7200"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                time.sleep(0.3)
            self._spawn(
                [sys.executable, str(HERE / "mock_llm.py"), str(self.mock_port), str(self.logs)],
                "mock.out",
                self.base,
                {"PATH": "/usr/bin:/bin", "HOME": str(self.home)},
            )
            self._spawn(
                [
                    self.opencode,
                    "serve",
                    "--port",
                    str(self.port),
                    "--print-logs",
                    "--log-level",
                    "debug",
                ],
                "server.log",
                self.ws,
                self.env(),
            )
            self._wait_ready()
        except BaseException:
            self.stop()
            raise

    def _wait_ready(self) -> None:
        deadline = time.time() + READY_TIMEOUT
        ids: list[str] = []
        while time.time() < deadline:
            for proc in self._procs:
                if proc.poll() is not None:
                    raise RigError(
                        f"a rig process exited early (rc {proc.returncode}); see {self.logs}"
                    )
            try:
                data = self.api("GET", "/api/provider")["data"]
                ids = [p["id"] for p in data]
            except (RigError, KeyError, TypeError):
                ids = []
            if ids:  # the list is [] for a few seconds after a cold start (lazy load)
                break
            time.sleep(0.5)
        assert_only_mock(ids)
        self.provider_ids = ids

    def stop(self) -> None:
        for proc in reversed(self._procs):
            _kill_group(proc)
        if self._ns is not None:
            _kill_group(self._ns)
        self._procs.clear()
        self._ns = None
        if self.logs.exists() and secret_in_logs(self.logs, self.password):
            raise RigError("the server password appears in the rig logs")

    # HTTP ----------------------------------------------------------------------------------

    def api(self, method: str, path: str, body: Any = None, *, timeout: float = 20.0) -> Any:
        url = f"http://127.0.0.1:{self.port}{path}"
        auth = base64.b64encode(f"{USER}:{self.password}".encode()).decode()
        data = None if body is None else json.dumps(body).encode()
        if self._ns is not None:
            return self._api_curl(method, url, auth, data, timeout)
        req = urllib.request.Request(
            url,
            data,
            {"authorization": f"Basic {auth}", "content-type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RigError(f"{method} {path} -> HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise RigError(f"{method} {path} failed: {exc}") from exc

    def _api_curl(
        self, method: str, url: str, auth: str, data: bytes | None, timeout: float
    ) -> Any:
        argv = [
            "curl",
            "-s",
            "-m",
            str(int(timeout)),
            "-X",
            method,
            url,
            "-H",
            f"authorization: Basic {auth}",
        ]
        argv += ["-H", "content-type: application/json", "-w", "\n%{http_code}"]
        if data is not None:
            argv += ["-d", data.decode()]
        out = subprocess.run(
            self._wrap(argv), capture_output=True, timeout=timeout + 5
        ).stdout.decode()
        text, _, code = out.rpartition("\n")
        if not code.startswith("2"):
            raise RigError(f"{method} {url} -> HTTP {code or '000'}")
        return _loads(text.encode())

    def new_session(self) -> str:
        return str(self.api("POST", "/api/session", {})["data"]["id"])

    def prompt(self, session_id: str, text: str) -> None:
        self.api("POST", f"/api/session/{session_id}/prompt", {"text": text})

    def bang(self, session_id: str, command: str) -> Any:
        """The TUI's ``!`` command: ``POST /api/session/:id/shell`` (no model, no agent tools)."""
        return self.api("POST", f"/api/session/{session_id}/shell", {"command": command})

    # observation ---------------------------------------------------------------------------

    def results(self) -> list[dict[str, Any]]:
        """Every tool result the mock model has received so far, in order."""
        path = self.logs / "results.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def wait_results(self, count: int, timeout: float = 30.0) -> list[dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            got = self.results()
            if len(got) >= count:
                return got
            time.sleep(0.25)
        raise RigError(
            f"expected {count} tool results, got {len(self.results())} within {timeout:g}s"
        )

    def debug(self, *args: str, attempts: int = 6) -> str:
        """``opencode debug ...`` in the isolated HOME (cwd = HOME), retried: the service lags."""
        self._ensure_service_port()
        last = ""
        for attempt in range(attempts):
            proc = subprocess.run(
                self._wrap([self.opencode, "debug", *args]),
                cwd=self.home,
                env=self.env(),
                capture_output=True,
                text=True,
                timeout=60,
            )
            last = proc.stdout
            if proc.returncode == 0 and last.strip() not in ("", "[]"):
                return last
            time.sleep(1 + attempt)
        return last

    def run(
        self, argv: Sequence[str], *, timeout: float = 120.0
    ) -> subprocess.CompletedProcess[str]:
        """Run a command in the rig's environment (netns included), cwd = the isolated HOME.

        The isolated service port is set first, so an ``opencode debug`` spawned by the command
        (Carter's installer calls it) can never reach the real service.
        """
        self._ensure_service_port()
        return subprocess.run(
            self._wrap(list(argv)),
            cwd=self.home,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _ensure_service_port(self) -> None:
        if getattr(self, "_service_port_set", False):
            return
        port = free_port()
        subprocess.run(
            self._wrap([self.opencode, "service", "set", "port", str(port)]),
            cwd=self.home,
            env=self.env(),
            capture_output=True,
            timeout=30,
        )
        self._service_port_set = True

    def stop_service(self) -> None:
        """Stop the isolated background service a ``debug`` call may have started."""
        if getattr(self, "_service_port_set", False):
            subprocess.run(
                self._wrap([self.opencode, "service", "stop"]),
                cwd=self.home,
                env=self.env(),
                capture_output=True,
                timeout=30,
            )


def _loads(raw: bytes) -> Any:
    return json.loads(raw) if raw.strip() else None


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
