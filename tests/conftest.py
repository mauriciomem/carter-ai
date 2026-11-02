"""Shared test fixtures for Carter installer tests."""

from __future__ import annotations

import json
import os
import pwd
import socket
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from carter import terminal
from carter.identity.rules import load_rules
from host_guard import (
    NetworkBlockedError,
    changed,
    digest_host,
    is_allowed_connect,
    is_local_host,
)

# Resolved once at import, before any fixture can redirect HOME. The hermetic fixture
# compares against it, so it must not be recomputed lazily.
_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()

# Fingerprint of the real host files (git config, OpenCode config, ~/.carter state) taken
# before any test runs; the session-end check fails the run if a test changed them.
_REAL_HOST_BEFORE = digest_host(_REAL_HOME)

# Ambient variables that change who git (or Carter) thinks the author is.
_IDENTITY_ENV_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "EMAIL",
    "CARTER_IDENTITY",
    "CARTER_IDENTITY_ROLE",
    "CARTER_IDENTITY_MODE",
)


# Ambient variables that would let a test reach the developer's agent, tokens or config.
_HOST_LEAK_VARS = (
    "SSH_AUTH_SOCK",
    "SSH_AGENT_PID",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GH_HOST",
    "GITHUB_API_URL",
    "OPENCODE_CONFIG",
    "OPENCODE_CONFIG_DIR",
    "OPENCODE_CONFIG_CONTENT",
)

# Tools a test must never run for real: name -> the fixture that provides a safe stand-in.
_GUARDED_TOOLS = {
    "gh": "fake_gh",
    "opencode": "fake_opencode",
    "ssh-keygen": "real_ssh_keygen",
}


def _is_under(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root)


@pytest.fixture(scope="session")
def real_home() -> Path:
    """The developer's real home directory (never write here)."""
    return _REAL_HOME


@pytest.fixture(autouse=True)
def _hermetic_env(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate every test from the developer's home, git config and identity env.

    Redirects ``HOME`` (what ``Path.home()``, hence ``~/.carter`` and
    ``~/.config/opencode``, resolve from), ``XDG_CONFIG_HOME`` and git's global/system
    config, and clears variables that override the git identity. The fixture home is
    separate from ``tmp_path`` so tests that list ``tmp_path`` do not see it.

    It asserts the isolation before the test body runs (and so before any git writer
    can), and fails the test if any location still points at the real home.
    """
    home = tmp_path_factory.mktemp("home").resolve()
    xdg = home / ".config"
    xdg.mkdir()
    gitconfig = home / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = Fixture Human\n\temail = fixture-human@example.invalid\n"
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # GIT_CONFIG_KEY_<n> / GIT_CONFIG_VALUE_<n> inject config pairs; clear every index.
    injected = [v for v in os.environ if v.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))]
    # The suite may run inside an agent shell (AGENT, OPENCODE_SESSION_ID...): AD1 would
    # then refuse every human-terminal command under test.
    signals = (*load_rules().agent_signals, *load_rules().human_signals)
    for var in (*_IDENTITY_ENV_VARS, *_HOST_LEAK_VARS, *signals, *injected):
        monkeypatch.delenv(var, raising=False)

    # Sockets and temp files must not leak out of the sandbox either (plan 003, step 5).
    runtime = home / ".run"
    runtime.mkdir(mode=0o700)
    tmpdir = home / "tmp"
    tmpdir.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setattr(tempfile, "tempdir", str(tmpdir))  # gettempdir() caches its answer
    # Subprocess git may only use local transports: no push or fetch can leave the machine.
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

    # Fail closed: a regression here would let a test write the real ~/.gitconfig.
    assert Path.home().resolve() == home, "Path.home() ignores HOME; tests are not hermetic"
    assert home != _REAL_HOME, "fixture home is the real home"
    assert _is_under(Path(os.environ["GIT_CONFIG_GLOBAL"]), home)
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    assert _is_under(Path(os.environ["XDG_RUNTIME_DIR"]), home)
    return home


@pytest.fixture(scope="session")
def real_host_digest() -> dict[str, str]:
    """Fingerprint of the real host files before the session started (hashes only)."""
    return dict(_REAL_HOST_BEFORE)


@pytest.fixture(scope="session", autouse=True)
def _real_host_untouched() -> Iterator[None]:
    """Fail the run if any test changed the developer's real git config, OpenCode config
    or ``~/.carter`` state (plan 003, step 5). Compares hashes taken at import time."""
    yield
    touched = changed(_REAL_HOST_BEFORE, digest_host(_REAL_HOME))
    assert not touched, f"tests modified the real host files: {', '.join(touched)}"


@pytest.fixture
def blocked_connections(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[str]]:
    """Block every non-loopback socket connect and name lookup in the test process.

    Yields the list of blocked attempts. A test that triggers the guard on purpose must
    ``clear()`` it; otherwise the teardown fails, even if the code under test swallowed
    the error. Loopback servers (``GITHUB_API_URL`` tests) and unix sockets under pytest's
    temp tree keep working. Subprocesses are covered separately (``GIT_ALLOW_PROTOCOL``,
    the ``gh``/``opencode`` stubs).
    """
    unix_root = tmp_path_factory.getbasetemp()
    blocked: list[str] = []

    def refuse(what: str) -> NetworkBlockedError:
        message = f"network access is blocked in tests: {what}"
        blocked.append(message)
        return NetworkBlockedError(message)

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: object) -> None:
        if not is_allowed_connect(address, self.family, unix_root):
            raise refuse(f"connect to {address!r}")
        real_connect(self, address)  # type: ignore[arg-type]

    def connect_ex(self: socket.socket, address: object) -> int:
        if not is_allowed_connect(address, self.family, unix_root):
            raise refuse(f"connect_ex to {address!r}")
        return real_connect_ex(self, address)  # type: ignore[arg-type]

    def getaddrinfo(host: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if not is_local_host(host):
            raise refuse(f"lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield blocked
    assert not blocked, "; ".join(blocked)


@pytest.fixture(autouse=True)
def _network_guard(blocked_connections: list[str]) -> None:
    """Every test runs with the network guard on."""


@pytest.fixture
def guard_bin(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A per-test bin dir, first on PATH, whose ``gh``/``opencode``/``ssh-keygen`` refuse to run.

    The stubs say which fixture to request. ``git`` is untouched (the real one, confined by the
    hermetic env). The rest of PATH is kept so Python, sh and git keep working.
    """
    bindir = tmp_path_factory.mktemp("guardbin").resolve()
    for tool, fixture in _GUARDED_TOOLS.items():
        stub = bindir / tool
        stub.write_text(
            "#!/bin/sh\n"
            f"echo \"carter test guard: the real '{tool}' must not run in tests; "
            f'request the {fixture} fixture" >&2\n'
            "exit 97\n"
        )
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    return bindir


@pytest.fixture(autouse=True)
def _tool_guard(guard_bin: Path) -> None:
    """Every test starts with the real ``gh``, ``opencode`` and ``ssh-keygen`` shadowed."""


@pytest.fixture
def real_ssh_keygen(guard_bin: Path) -> None:
    """Opt in to the real ``ssh-keygen`` (offline key generation and signature checks)."""
    (guard_bin / "ssh-keygen").unlink(missing_ok=True)


@pytest.fixture
def pollute_git_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Return a function that sets every env var able to hijack the commit identity.

    Used to prove ``state.py`` commits stay human/human and unsigned (plan 002, step 11).
    The function takes an optional ``monkeypatch`` (defaults to the test's own) so it can
    also be driven from another fixture; the changes are undone with that monkeypatch.
    """

    def pollute(mp: pytest.MonkeyPatch | None = None) -> None:
        mp = mp or monkeypatch
        mp.setenv("GIT_AUTHOR_NAME", "Polluter")
        mp.setenv("GIT_AUTHOR_EMAIL", "polluter-author@example.invalid")
        mp.setenv("GIT_COMMITTER_NAME", "Polluter")
        mp.setenv("GIT_COMMITTER_EMAIL", "polluter-committer@example.invalid")
        mp.setenv("GIT_CONFIG_COUNT", "1")
        mp.setenv("GIT_CONFIG_KEY_0", "user.name")
        mp.setenv("GIT_CONFIG_VALUE_0", "Polluter Config")
        mp.setenv("CARTER_IDENTITY", "polluter")
        mp.setenv("CARTER_IDENTITY_ROLE", "author")
        mp.setenv("CARTER_IDENTITY_MODE", "review")

    return pollute


@pytest.fixture
def repo_root() -> Path:
    """Path to the Carter repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Temporary base directory for testing (overrides ~/.config, ~/.carter etc.)."""
    return tmp_path


@pytest.fixture
def fake_opencode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Put a fake ``opencode`` on an isolated PATH.

    Call it with the ``--version`` output to emit, or ``None`` for "not installed".
    PATH holds only the fake bin dir, so a real ``opencode`` can never leak in.
    """

    def make(
        version_output: str | None = "opencode v2.1.4",
        agents_output: str = "[]",
        agents_exit: int = 0,
        agents_sequence: list[str] | None = None,
        config_output: str | None = None,
        config_exit: int = 0,
        config_sequence: list[str] | None = None,
    ) -> Path:
        """``agents_output``/``agents_exit`` drive ``opencode debug agents``.

        ``agents_sequence`` serves one output per call (repeating the last), to
        mimic OpenCode's service returning stale data before fresh data.

        ``config_output``/``config_exit``/``config_sequence`` do the same for
        ``opencode debug config`` (the resolved config the policy writer verifies against).
        Left unset, ``debug config`` fails loudly (exit 2) rather than answering with the
        agents list. Output is served byte for byte (no newline is added).
        """
        bindir = tmp_path / "fakebin"
        bindir.mkdir(exist_ok=True)
        script = bindir / "opencode"
        if version_output is None:
            script.unlink(missing_ok=True)
        else:
            outputs = agents_sequence or [agents_output]
            for i, out in enumerate(outputs, 1):
                (bindir / f"agents.{i}.out").write_text(out)
            counter = bindir / "agents.calls"
            counter.write_text("0")
            for stale in bindir.glob("config.*.out"):
                stale.unlink()
            config_outputs = config_sequence or (
                [config_output] if config_output is not None else []
            )
            for i, out in enumerate(config_outputs, 1):
                (bindir / f"config.{i}.out").write_text(out)
            config_counter = bindir / "config.calls"
            config_counter.write_text("0")
            config_branch = (
                f'  n=$(( $(/bin/cat "{config_counter}") + 1 )); echo "$n" > "{config_counter}"\n'
                f'  [ "$n" -gt {len(config_outputs)} ] && n={len(config_outputs)}\n'
                f'  /bin/cat "{bindir}/config.$n.out"; exit {config_exit}\n'
                if config_outputs
                else "  echo \"fake_opencode: config_output not set for 'debug config'\" >&2\n"
                "  exit 2\n"
            )
            script.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = debug ] && [ "$2" = config ]; then\n'
                f"{config_branch}"
                "fi\n"
                'if [ "$1" = debug ]; then\n'
                f'  n=$(( $(/bin/cat "{counter}") + 1 )); echo "$n" > "{counter}"\n'
                f'  [ "$n" -gt {len(outputs)} ] && n={len(outputs)}\n'
                f'  /bin/cat "{bindir}/agents.$n.out"; exit {agents_exit}\n'
                "fi\n"
                f"printf '%s\\n' '{version_output}'\n"
            )
            script.chmod(0o755)
        # PATH holds only the fakes: a real opencode (or git) can never leak in. A fake gh
        # requested earlier stays reachable.
        dirs = [bindir, *([tmp_path / "fakegh"] if (tmp_path / "fakegh").is_dir() else [])]
        monkeypatch.setenv("PATH", os.pathsep.join(str(d) for d in dirs))
        return bindir

    return make


_FAKE_GH = """#!{python}
import json, os, sys

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "gh.json")) as fh:
    config = json.load(fh)
argv = sys.argv[1:]
with open(os.path.join(here, "gh.calls"), "a") as fh:
    fh.write(json.dumps(argv) + "\\n")
with open(os.path.join(here, "gh.env"), "a") as fh:
    names = ("GH_TOKEN", "GITHUB_TOKEN", "GH_PROMPT_DISABLED")
    fh.write(json.dumps({{n: os.environ.get(n) for n in names}}) + "\\n")
for i, arg in enumerate(argv):
    path = None
    if arg.startswith("--body-file="):
        path = arg.split("=", 1)[1]
    elif arg == "--body-file" and i + 1 < len(argv):
        path = argv[i + 1]
    if path:
        try:
            mode, text = oct(os.stat(path).st_mode & 0o777), open(path).read()
        except OSError:
            mode, text = None, None
        with open(os.path.join(here, "gh.bodies"), "a") as fh:
            fh.write(json.dumps({{"path": path, "mode": mode, "content": text}}) + "\\n")
reply, matched = config["default"], -1
for prefix, candidate in config["rules"].items():
    words = prefix.split()
    if argv[: len(words)] == words and len(words) > matched:
        reply, matched = candidate, len(words)
sys.stdout.write(reply.get("stdout", ""))
sys.stderr.write(reply.get("stderr", ""))
sys.exit(reply.get("rc", 0))
"""


@dataclass(frozen=True)
class FakeGh:
    """Handle on the fake ``gh``: where it lives and what it was asked to do."""

    bindir: Path

    def calls(self) -> list[list[str]]:
        """Every invocation so far, as its argument list (oldest first)."""
        log = self.bindir / "gh.calls"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def _lines(self, name: str) -> list[dict[str, Any]]:
        log = self.bindir / name
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def bodies(self) -> list[dict[str, Any]]:
        """Each ``--body-file`` seen at call time: its path, mode (octal string) and content."""
        return self._lines("gh.bodies")

    def envs(self) -> list[dict[str, Any]]:
        """For each call, the token-related variables the process was given."""
        return self._lines("gh.env")


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeGh]:
    """Put a fake ``gh`` first on PATH (the rest of PATH stays, so ``git`` still works).

    ``fake_gh(stdout="", stderr="", rc=0, rules=None)`` scripts the replies: ``rules`` maps
    an argument prefix (``"auth status"``) to ``{"stdout", "stderr", "rc"}``; the longest
    matching prefix wins, otherwise the default reply is used. Every call is recorded in
    ``.calls()``. Calling it again replaces the script and keeps the call log.
    """

    def make(
        stdout: str = "",
        stderr: str = "",
        rc: int = 0,
        rules: dict[str, dict[str, object]] | None = None,
    ) -> FakeGh:
        bindir = tmp_path / "fakegh"
        bindir.mkdir(exist_ok=True)
        (bindir / "gh.json").write_text(
            json.dumps(
                {"default": {"stdout": stdout, "stderr": stderr, "rc": rc}, "rules": rules or {}}
            )
        )
        script = bindir / "gh"
        script.write_text(_FAKE_GH.format(python=sys.executable))
        script.chmod(0o755)
        entries = os.environ.get("PATH", "").split(os.pathsep)
        if str(bindir) not in entries:
            monkeypatch.setenv("PATH", os.pathsep.join([str(bindir), *entries]))
        return FakeGh(bindir)

    return make


@pytest.fixture(autouse=True)
def _no_real_opencode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``carter check`` from running a developer's real ``opencode``.

    Tests that want the harness step opt in via the ``fake_opencode`` fixture.
    """
    if "fake_opencode" in request.fixturenames:
        return
    import carter.harness

    monkeypatch.setattr(carter.harness, "_which", lambda _cmd: None)


@pytest.fixture
def github_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A loopback fake of api.github.com; ``GITHUB_API_URL`` points at it for the test."""
    from gh_api import FakeGitHub

    api = FakeGitHub().start()
    monkeypatch.setenv("GITHUB_API_URL", api.url)
    yield api
    api.stop()


@pytest.fixture
def human_tty(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    """Make the process look like a human at a terminal (or not). CliRunner swaps the
    streams for pipes, so the TTY test is faked at the one place commands ask."""

    def set_tty(on: bool = True) -> None:
        monkeypatch.setattr(terminal, "_isatty", lambda _stream: on)

    return set_tty


@pytest.fixture(autouse=True)
def _no_real_verify_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard writer re-reads OpenCode's config with real pauses (a service that reloads
    asynchronously); tests that rely on it say so by patching ``_sleep`` themselves."""
    from carter.guard import configwrite

    monkeypatch.setattr(configwrite, "_sleep", lambda _seconds: None)
