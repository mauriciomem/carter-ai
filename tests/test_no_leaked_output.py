"""Nothing an external program prints may reach the user's terminal through a Carter command.

OpenCode (and the service it starts) can print its own lines: a server URL, a banner. Carter
runs it to read JSON, so everything it writes must be captured, and it must not be able to write
to the terminal behind our back (`/dev/tty`). The command runs on a real pseudo-terminal, so a
leak would show in the transcript.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from carter.guard.state import GuardState, save
from carter.install.paths import guard_state_path
from ssh_rig import pty_run

URL = "http://127.0.0.1:49374"
FAKE = f"""#!/bin/sh
# a noisy opencode: the URL goes to stdout (before the JSON, as a banner would), to stderr and to
# the controlling terminal; it also leaves a mark so the test knows it ran
echo "$0 $*" >> "{{log}}"
echo "{URL}" >&2
echo "{URL}" > /dev/tty 2>/dev/null
case "$*" in
  *--version*) echo "opencode v2.1.4" ;;
  *) echo "[]" ;;
esac
"""


@pytest.fixture
def noisy_opencode(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bindir = tmp_path / "noisy-bin"
    bindir.mkdir()
    log = tmp_path / "opencode.calls"
    exe = bindir / "opencode"
    exe.write_text(FAKE.replace("{log}", str(log)))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "LC_ALL": "C.UTF-8"}
    return env, log


def installed_state() -> None:
    state = GuardState()
    for name in ("g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit"):
        state.consent(name, "accepted", "2026-11-09", 3 if name == "g2" else 2)
    path = guard_state_path(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    save(state, path)


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "--host"],
        ["check", "--host", "-v"],
        ["guard", "status"],
        ["guard", "install", "--dry-run"],
    ],
    ids=lambda a: " ".join(a),
)
def test_a_noisy_opencode_never_reaches_the_terminal(
    argv: list[str], noisy_opencode: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, log = noisy_opencode
    installed_state()
    done = pty_run([sys.executable, "-m", "carter.cli", *argv], env, [], cwd=tmp_path, timeout=90)
    assert done.rc in (0, 1), done.output
    assert URL not in done.output, done.output
    if argv[0] == "check" or argv[1] == "install":
        assert log.exists(), "the fake opencode was never run: the test proves nothing"
