"""The one subprocess entry of A+ (plan 003 step 18; RFC-0007 App C.5 "Hardened git calls").

Every git, ssh and ssh-keygen call the A+ building blocks make goes through here, so the
environment is scrubbed in exactly one place: a polluted shell cannot pick the author,
inject config (``GIT_CONFIG_COUNT``/``KEY_n``/``PARAMETERS``) or point git at another
repository; system config is never read; prompts and pagers are off; and the agent socket is
not passed (these calls only read). ``GIT_CONFIG_GLOBAL`` is kept: it is where the human's
own config lives, which is what the checks must see.

``git()`` also neutralises what could execute during a read: ``core.fsmonitor``, repo hooks
(``core.hooksPath`` points at an empty directory), credential helpers, askpass and the pager.
Pass ``harden=False`` only for the config listing itself, whose ``-c`` pairs would otherwise
show up as ``command``-scope entries.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import functools
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

from carter.identity.scrub import scrub_git_env

DEFAULT_TIMEOUT = 30.0
NETWORK_TIMEOUT = 300.0


_FORCED: contextvars.ContextVar[Mapping[str, str] | None] = contextvars.ContextVar(
    "carter_aplus_forced_env", default=None
)


@contextlib.contextmanager
def forced_env(env: Mapping[str, str]) -> Iterator[None]:
    """Make every ``clean_env()`` start from ``env`` instead of the process environment.

    B uses this so that its read-only git calls (config listing, range, signatures) never see
    the OpenCode server's environment: the base is built from scratch, then scrubbed as usual."""
    token = _FORCED.set(dict(env))
    try:
        yield
    finally:
        _FORCED.reset(token)


class RunError(Exception):
    """A tool is missing, not executable, or did not finish in time."""


@functools.cache
def empty_hooks_dir() -> str:
    """A Carter-owned empty directory for ``core.hooksPath`` (removed when the process exits)."""
    path = tempfile.mkdtemp(prefix="carter-nohooks-")
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def clean_env(
    base: Mapping[str, str] | None = None, *, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """A scrubbed copy of ``base`` (default: the process environment) for a read-only call."""
    forced = _FORCED.get()
    env = scrub_git_env(
        base if base is not None else (forced if forced is not None else os.environ)
    )
    env.pop("SSH_AUTH_SOCK", None)
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        SSH_ASKPASS_REQUIRE="never",
        GIT_PAGER="cat",
        LC_ALL="C",
    )
    env.update(extra or {})
    return env


def run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` (no shell) with a scrubbed environment; a non-zero exit is returned."""
    try:
        return subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else clean_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            stdin=None if input_text is not None else subprocess.DEVNULL,
            check=False,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise RunError(f"{Path(argv[0]).name} not found or not executable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunError(f"{Path(argv[0]).name} timed out after {timeout:g}s") from exc


def hardening() -> list[str]:
    pairs = [
        "core.fsmonitor=false",
        f"core.hooksPath={empty_hooks_dir()}",
        "credential.helper=",
        "core.askPass=",
        "core.pager=cat",
    ]
    return [arg for pair in pairs for arg in ("-c", pair)]


def git(
    args: Sequence[str],
    cwd: Path,
    *,
    harden: bool = True,
    config: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """``git [hardening] [-c extra ...] --no-pager <args>`` in ``cwd``."""
    prefix = hardening() if harden else []
    extra = [arg for pair in config for arg in ("-c", pair)]
    return run(["git", *prefix, *extra, "--no-pager", *args], cwd=cwd, env=env, timeout=timeout)


def network_git(
    args: Sequence[str], cwd: Path, *, timeout: float = NETWORK_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """``git`` for ``fetch`` and ``push`` only: the human's own credentials stay in reach.

    Unlike ``git()``, the credential helpers, ``SSH_AUTH_SOCK``, system config and stdin
    (for a passphrase or password prompt) are left alone, because the point of ``carter
    push`` is that *you* authenticate. What could run repository-controlled code is still
    off: hooks (``core.hooksPath`` is an empty directory), ``core.fsmonitor`` and the pager.
    ``push.followTags`` is forced off so a configured default cannot add tags. The caller has
    already refused repository configs that name a helper, a proxy or an SSH command.
    Output is captured so the caller can mask URLs before printing it.
    """
    env = scrub_git_env(os.environ)
    env.update(GIT_PAGER="cat", LC_ALL="C")
    pairs = [
        "core.fsmonitor=false",
        f"core.hooksPath={empty_hooks_dir()}",
        "core.pager=cat",
        "push.followTags=false",
    ]
    prefix = [arg for pair in pairs for arg in ("-c", pair)]
    try:
        return subprocess.run(
            ["git", *prefix, "--no-pager", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise RunError("git not found or not executable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunError(f"git timed out after {timeout:g}s") from exc


GH_TIMEOUT = 60.0
# Carter never sets these; they are named so a stale one can be reported (names only).
GH_TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


def gh_path() -> str | None:
    """Absolute path of the ``gh`` found on ``PATH`` (``None`` if there is none)."""
    found = shutil.which("gh")
    return os.path.abspath(found) if found else None


def gh(
    args: Sequence[str], cwd: Path, *, timeout: float = GH_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` by absolute path with your own login: no token is set or forced here.

    The environment is yours minus the git author/config/repository overrides; prompts, the
    pager, colour and the update check are off. Output is captured for the caller to mask.
    """
    exe = gh_path()
    if exe is None:
        raise RunError("gh not found: install the GitHub CLI and run `gh auth login`")
    env = scrub_git_env(os.environ)
    env.update(
        GH_PROMPT_DISABLED="1",
        GH_NO_UPDATE_NOTIFIER="1",
        GH_PAGER="cat",
        NO_COLOR="1",
        LC_ALL="C",
    )
    try:
        return subprocess.run(
            [exe, *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise RunError("gh not found or not executable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunError(f"gh timed out after {timeout:g}s") from exc
