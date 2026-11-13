"""What ``carter install`` and ``carter uninstall`` print when they finish.

Both turn a result object into the layout of :mod:`carter.ui` (header, sections, aligned rows).
Nothing here touches the disk: the same data always prints the same text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from carter import ui
from carter.home import tilde
from carter.install.backups import RETENTION_DAYS
from carter.ui import Row

if TYPE_CHECKING:
    from carter.install.uninstall import UninstallReport


@dataclass
class InstallReport:
    """What ``install`` did: per-file statuses (``created``/``updated``/``unchanged``)."""

    agents: dict[str, int]
    skills: dict[str, int]  # the statuses count files; "skills" counts directories
    knowledge: int = 0  # new knowledge files
    config_created: bool = False
    pruned: int = 0  # old backup folders removed
    guards: list[str] = field(default_factory=list)  # accepted guard groups, none if skipped
    replaced: int = 0  # edited files copied to ``backup_dir`` before being overwritten
    backup_dir: Path = Path()


def _changes(stats: dict[str, int]) -> str:
    """``new`` / ``up to date`` / ``2 new, 1 updated`` from per-file statuses."""
    made, updated = stats["created"], stats["updated"]
    if made and not updated and not stats["unchanged"]:
        return "new"
    changed = [f"{n} {word}" for n, word in ((made, "new"), (updated, "updated")) if n]
    return ", ".join(changed) or "up to date"


def render_install(report: InstallReport) -> None:
    """The ``Installed`` table, then one warning line if edited files were replaced."""
    agents = report.agents
    table = [
        Row(
            "agents", agents["created"] + agents["updated"] + agents["unchanged"], _changes(agents)
        ),
        Row("skills", report.skills["skills"], _changes(report.skills)),
    ]
    if report.knowledge:
        table.append(Row("knowledge files", report.knowledge, "new"))
    if report.config_created:
        table.append(Row("config.toml", None, "created"))
    if report.pruned:
        table.append(
            Row("old backups", report.pruned, f"removed, older than {RETENTION_DAYS} days")
        )
    if report.guards:
        table.append(Row("guards", None, " · ".join(report.guards)))
    ui.section("Installed", "ok")
    ui.rows(table)
    if report.replaced:
        n = report.replaced
        title = f"Replaced {n} file{'s' if n != 1 else ''} you had edited"
        ui.section(title, "warn", f"copies in {tilde(report.backup_dir)}/")


# The Removed section: (key in ``report.removed``, label, whether it shows a count).
_REMOVED = (
    ("guards", "guards", False),
    ("identity", "LLM identity", False),
    ("agents", "agents", True),
    ("skills", "skills", True),
    ("plugin", "plugin", False),
    ("AGENTS.md", "AGENTS.md", False),
    ("MCP servers", "MCP servers", True),
    ("knowledge", "knowledge files", True),
    ("other", "other files", True),
)


def _removed_rows(report: UninstallReport) -> list[Row]:
    found = {**report.removed, "MCP servers": report.mcp_servers}
    table = [
        Row(label, found[key] if counted else None)
        for key, label, counted in _REMOVED
        if found.get(key)
    ]
    if report.config_removed:
        table.append(Row("config.toml", None, "was all defaults"))
    return table


def _kept_rows(report: UninstallReport) -> list[Row]:
    table = [Row(tilde(path), None, "you edited it") for path in report.kept_files]
    for row in report.kept:
        table.append(Row(tilde(row.path) + ("/" if row.dir else ""), row.count, row.reason))
    return table


def _workspace_rows(report: UninstallReport) -> list[Row]:
    table = []
    for w in report.workspaces:
        if not w.exists:
            table.append(Row(tilde(w.path), None, "no longer exists"))
        elif w.rm:
            table.append(Row(tilde(w.path), None, w.rm, cmd=True))
        else:
            table.append(Row(tilde(w.path), None, "no Carter agents left"))
    return table


def _also(report: UninstallReport) -> None:
    """``also yours to delete``: one line when every workspace has the same list, else one each."""
    named = [w for w in report.workspaces if w.exists and w.also]
    if len({w.also for w in named}) == 1:
        ui.info(f"also yours to delete: {', '.join(named[0].also)}", indent=ui.INDENT)
        return
    for w in named:
        ui.info(f"{tilde(w.path)}: also yours to delete: {', '.join(w.also)}", indent=ui.INDENT)


def render_uninstall(report: UninstallReport) -> None:
    """The sections of the report, the verdict and the last steps (the caller printed the header).

    Only the two ``!`` sections go to stderr; everything else is data on stdout."""
    removed = _removed_rows(report)
    if removed:
        ui.section("Removed", "ok")
        ui.rows(removed)
    if report.edited_copies:
        ui.section("Removed although you edited them", "warn")
        edited = [Row(tilde(p), fix=f"copy: {tilde(copy)}") for p, copy in report.edited_copies]
        ui.rows(edited, paths=True, err=True)
    kept = _kept_rows(report)
    if kept:
        ui.section("Kept, because they are yours")
        ui.rows(kept, paths=True)
    if report.workspaces:
        ui.section("Workspaces, not touched", note="Carter files you can remove")
        ui.rows(_workspace_rows(report), paths=True)
        _also(report)
    ui.gap()
    ui.ok("Uninstalled", "" if removed else "nothing was left to remove", strong=True)
    todo = [("last step, remove the command", report.manager)]
    if report.leftover:
        todo.append(("to delete everything Carter kept", report.rm_all))
    ui.steps(todo)
