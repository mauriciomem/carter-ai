"""Test doubles for B (plan 007 step 4): a fake ``ssh`` that runs receive-pack locally.

The fake lives in a directory used as ``[identity.signing] ssh_bin_dir``. B pushes with
``-c core.sshCommand=<ssh_bin_dir>/ssh``, so this is the only seam: no environment variable, no
``url.<x>.insteadOf`` (a global ``insteadOf`` that matches the origin makes B refuse). The fake
maps the path of ``git-receive-pack '<path>'`` below ``<dir>/remote-root``, so
``git@github.com:o/r.git`` lands in ``<dir>/remote-root/o/r.git``.

Records: ``ssh.calls`` (one JSON line per call: argv and the NAMES of the environment variables,
never values). ``ssh -G`` prints ``ssh_g.txt`` (a captured fixture) when it exists.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FAKE_SSH = """#!{python}
import json, os, shlex, sys
here = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
with open(os.path.join(here, "ssh.calls"), "a") as fh:
    fh.write(json.dumps({{"argv": argv, "env_names": sorted(os.environ)}}) + "\\n")
if "-G" in argv:
    fixture = os.path.join(here, "ssh_g.txt")
    sys.stdout.write(open(fixture).read() if os.path.exists(fixture) else "host github.com\\n")
    sys.exit(0)
withval = set("opplFJbcEeLRDSwWiI")
i = 0
while i < len(argv):
    a = argv[i]
    if a == "--":
        i += 1
        break
    if a.startswith("-") and len(a) > 1:
        i += 2 if (a[1] in withval and len(a) == 2) else 1
        continue
    break
words = shlex.split(" ".join(argv[i + 1:]))
if len(words) != 2 or words[0] not in ("git-receive-pack", "git-upload-pack"):
    sys.stderr.write("fake-ssh: unexpected remote command\\n")
    sys.exit(255)
root = os.path.join(here, "remote-root")
target = os.path.normpath(os.path.join(root, words[1].lstrip("/")))
if not target.startswith(root + os.sep):
    sys.stderr.write("fake-ssh: path escapes the remote root\\n")
    sys.exit(255)
os.execvp("git", ["git", words[0].split("-", 1)[1], target])
"""


@dataclass(frozen=True)
class FakeSsh:
    """Handle on a fake-ssh directory (also usable as ``ssh_bin_dir``)."""

    bindir: Path

    @property
    def root(self) -> Path:
        return self.bindir / "remote-root"

    def calls(self) -> list[dict[str, Any]]:
        log = self.bindir / "ssh.calls"
        return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

    def reset(self) -> None:
        (self.bindir / "ssh.calls").unlink(missing_ok=True)

    def set_ssh_g(self, text: str | None) -> None:
        target = self.bindir / "ssh_g.txt"
        if text is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(text)

    def bare(self, owner: str = "o", repo: str = "r") -> Path:
        return self.root / owner / f"{repo}.git"

    def link_real_tools(self) -> None:
        """Symlink the real ssh-keygen, ssh-add and ssh-agent next to the fake ``ssh``."""
        for name in ("ssh-keygen", "ssh-add", "ssh-agent"):
            found = shutil.which(name)
            if found and not (self.bindir / name).exists():
                (self.bindir / name).symlink_to(found)

    def ssh_command(self) -> str:
        """The value B passes as ``core.sshCommand`` (an absolute path)."""
        return str(self.bindir / "ssh")


def install_fake_ssh(directory: Path) -> FakeSsh:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "ssh"
    script.write_text(FAKE_SSH.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (directory / "remote-root").mkdir(exist_ok=True)
    os.chmod(directory, 0o755)
    return FakeSsh(directory)
