"""The SSH client-config check.

1. A **textual** scan of ``~/.ssh/config`` and the files it ``Include``s for ``Match ... exec``,
   because ``ssh -G`` itself would run that command. If it finds one, ``ssh -G`` is not run.
2. ``<ssh_bin_dir>/ssh -G git@github.com`` (offline: it prints the effective config and exits),
   flagging ``ProxyCommand``, ``LocalCommand``, ``PermitLocalCommand yes`` and
   ``KnownHostsCommand``. ``ssh_bin_dir`` defaults to ``/usr/bin`` (Apple OpenSSH) and is the
   only place ``ssh`` is looked up: never ``$PATH`` order.

The broker refuses on these findings (``E-B-REPOCFG``, "ssh config"); `carter push` shows them
and asks. A finding
names the option and the file, never its value. The system-wide ``/etc/ssh/ssh_config`` is
admin-owned and not scanned textually (``ssh -G`` still reports what it sets).
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path

from carter.aplus import run
from carter.aplus.findings import Finding, to_error
from carter.identity.errors import E_B_REPOCFG

__all__ = ["check_ssh_config", "parse_ssh_g", "scan_match_exec", "to_error"]

DEFAULT_SSH_BIN_DIR = "/usr/bin"
MAX_INCLUDE_DEPTH = 8
_MATCH = re.compile(r"^\s*match(?:\s+|\s*=\s*)(.*)$", re.IGNORECASE)
_INCLUDE = re.compile(r"^\s*include(?:\s+|\s*=\s*)(.*)$", re.IGNORECASE)
_COMMAND_OPTIONS = ("proxycommand", "localcommand", "knownhostscommand")


def _finding(key: str, origin: str, reason: str) -> Finding:
    return Finding(E_B_REPOCFG, "ssh config", key, origin, reason)


def _include_targets(arguments: str, ssh_dir: Path) -> list[Path]:
    out: list[Path] = []
    for token in arguments.replace('"', " ").split():
        pattern = os.path.expanduser(token)
        if not os.path.isabs(pattern):
            pattern = str(ssh_dir / pattern)
        out += [Path(p) for p in sorted(glob.glob(pattern))]
    return out


def _runs_command(criteria: str) -> bool:
    """Does a ``Match`` line carry an ``exec`` criterion? ``ssh -G`` runs it.

    ``Match !exec "cmd"`` and ``Match exec="cmd"`` run too, so a token counts when, lower-cased
    and stripped of ``!``, quotes, it is ``exec`` or starts with ``exec=``."""
    for token in criteria.replace('"', " ").replace("'", " ").split():
        word = token.lower().lstrip("!")
        if word == "exec" or word.startswith("exec="):
            return True
    return False


def scan_match_exec(home: Path) -> list[Finding]:
    """Findings for ``Match ... exec`` in ``~/.ssh/config`` and everything it includes."""
    ssh_dir = home / ".ssh"
    root = ssh_dir / "config"
    found: list[Finding] = []
    seen: set[Path] = set()

    def visit(path: Path, depth: int) -> None:
        real = Path(os.path.realpath(path))
        if real in seen or not path.is_file():
            return
        seen.add(real)
        if depth > MAX_INCLUDE_DEPTH:
            found.append(
                _finding("Include", str(path), "include chain deeper than the cap, not checked")
            )
            return
        try:
            text = path.read_text(errors="replace")
        except OSError:
            found.append(
                _finding("Include", str(path), "cannot read the file, so it cannot be checked")
            )
            return
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            match = _MATCH.match(line)
            if match and _runs_command(match.group(1)):
                found.append(
                    _finding("Match exec", str(path), f"line {number}: ssh -G would run it")
                )
            include = _INCLUDE.match(line)
            if include:
                for target in _include_targets(include.group(1), ssh_dir):
                    visit(target, depth + 1)

    visit(root, 0)
    return found


def parse_ssh_g(output: str) -> list[Finding]:
    """Findings in ``ssh -G`` output; option values are never kept."""
    found = []
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        option, value = parts[0].lower(), parts[1].strip().lower()
        if option in _COMMAND_OPTIONS and value != "none":
            found.append(_finding(option, "", "runs a command when the connection is made"))
        elif option == "permitlocalcommand" and value in ("yes", "true"):
            found.append(_finding(option, "", "allows LocalCommand to run"))
    return found


def check_ssh_config(
    home: Path,
    *,
    ssh_bin_dir: str | Path = DEFAULT_SSH_BIN_DIR,
    host: str = "github.com",
    user: str = "git",
) -> list[Finding]:
    """Pre-scan, then ``ssh -G <user>@<host>``; a missing or failing ``ssh`` is a finding.

    ``-G git@github.com`` (not the bare host) so that ``Match user git`` blocks apply, as they
    will in the push. ``home`` must be the directory OpenSSH reads:
    the passwd home, not ``$HOME``."""
    found = scan_match_exec(home)
    if found:
        return found
    ssh = Path(ssh_bin_dir) / "ssh"
    try:
        proc = run.run(
            [str(ssh), "-G", f"{user}@{host}"], env=run.clean_env(extra={"HOME": str(home)})
        )
    except run.RunError:
        return [_finding("ssh", str(ssh), "cannot run ssh, so the SSH config cannot be checked")]
    if proc.returncode != 0:
        return [
            _finding(
                "ssh -G", str(ssh), f"exited {proc.returncode}, so the config cannot be checked"
            )
        ]
    return parse_ssh_g(proc.stdout)
