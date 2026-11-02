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
import functools
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from carter.identity.scrub import scrub_git_env

DEFAULT_TIMEOUT = 30.0


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
    env = scrub_git_env(os.environ if base is None else base)
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
