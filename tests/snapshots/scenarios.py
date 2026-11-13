"""The six report scenarios, with fake but realistic data (user ``u``, home ``/home/u``).

``play`` prints one of them through the real renderers into a fake terminal. The golden tests and
the render lab both use it, so what a person approves is what the tests pin.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from unittest import mock

from carter import ui
from carter.install.reports import InstallReport, render_install, render_uninstall
from carter.install.uninstall import KeptRow, UninstallReport, Workspace
from snapshots.term import Term

VERSION = "v0.19.2"
NEXT_STEP = "restart the OpenCode server from a clean terminal to load the agents and plugin"
GUARDS = ["g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit"]
HOME = Path("/home/u")
BACKUP = HOME / ".carter/backups/20261112T101500"
OC = HOME / ".config/opencode"
NOTICE = "gh CLI not found (optional)"  # what a machine without the GitHub CLI prints

FILES = {"created": 0, "updated": 0, "unchanged": 0}


def _stats(**counts: int) -> dict[str, int]:
    return {**FILES, **counts}


INSTALL = {
    "install-clean": InstallReport(
        agents=_stats(created=8),
        skills=_stats(created=27, skills=27),
        knowledge=4,
        config_created=True,
        guards=GUARDS,
    ),
    "install-rerun": InstallReport(
        agents=_stats(unchanged=8), skills=_stats(unchanged=27, skills=27), guards=GUARDS
    ),
    "install-edited": InstallReport(
        agents=_stats(updated=1, unchanged=7),
        skills=_stats(updated=2, unchanged=25, skills=27),
        pruned=2,
        guards=GUARDS,
        replaced=3,
        backup_dir=BACKUP,
    ),
}

_REMOVED = {"guards": 1, "agents": 8, "skills": 27, "plugin": 1, "AGENTS.md": 1, "knowledge": 4}

UNINSTALL = {
    "uninstall-clean": UninstallReport(
        removed=_REMOVED, config_removed=True, manager="uv tool uninstall carter-ai"
    ),
    "uninstall-full": UninstallReport(
        removed={**_REMOVED, "skills": 25},
        mcp_servers=2,
        config_removed=True,
        edited_copies=[
            (OC / "agents/carter-pm.md", BACKUP / ".config/opencode/agents/carter-pm.md")
        ],
        kept_files=[OC / "skills/carter-adr/SKILL.md", OC / "skills/carter-distill/SKILL.md"],
        kept=[
            KeptRow(HOME / ".carter/memories", "your notes", 12),
            KeptRow(HOME / ".carter/knowledge", "files you edited or added", 2),
            KeptRow(HOME / ".carter/state/audit", "push approvals, ops log, guard log", 3),
            KeptRow(HOME / ".carter/secrets", "revoke the token on GitHub too", 1),
            KeptRow(HOME / ".carter/backups", "copies of files Carter replaced", 4),
        ],
        workspaces=[
            Workspace(
                HOME / "src/proj",
                exists=True,
                rm="rm /home/u/src/proj/.opencode/agents/carter-*.md",
                also=(".carter/", "AGENTS.md", ".github/workflows/carter-review.yml"),
            ),
            Workspace(HOME / "src/infra", exists=False),
        ],
        manager="uv tool uninstall carter-ai",
        leftover=True,
        rm_all="rm -r /home/u/.carter",
    ),
    "uninstall-noop": UninstallReport(manager="uv tool uninstall carter-ai"),
}

NAMES = (*INSTALL, *UNINSTALL)
_FOREIGN = ("NO_COLOR", "COLORTERM", "FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE")


def play(name: str, kind: str, *, columns: int = 100, no_color: bool = False) -> Term:
    """Print scenario ``name`` as the command would, on a ``kind`` terminal ``columns`` wide."""
    term = Term(kind)
    env = {"HOME": str(HOME), "COLUMNS": str(columns), "TERM": "xterm-256color"}
    with mock.patch.dict(os.environ, env), contextlib.ExitStack() as stack:
        for key in _FOREIGN:
            os.environ.pop(key, None)
        if no_color:
            os.environ["NO_COLOR"] = "1"
        stack.enter_context(contextlib.redirect_stdout(term.out))  # type: ignore[type-var]
        stack.enter_context(contextlib.redirect_stderr(term.err))  # type: ignore[type-var]
        if name in INSTALL:
            ui.header("Carter install", VERSION)
            ui.warn(NOTICE)
            render_install(INSTALL[name])
            ui.gap()
            ui.next(NEXT_STEP)
        else:
            ui.header("Carter uninstall", VERSION)
            render_uninstall(UNINSTALL[name])
    return term
