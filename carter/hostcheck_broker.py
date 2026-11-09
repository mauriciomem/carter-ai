"""The push tool items of ``carter check --host``.

Read-only and names only: no environment value, no socket path, no commit text, no title ever
reaches an item. What it reports:

- whether the push tool are on (``isolation.json`` ``b_enabled``) and whether that agrees with the
  ``g2`` revision in guard state (a mismatch in either direction is not silent);
- the headless profile, against its recorded hash;
- the audit store (directory and file modes; counts of decisions, nothing else);
- the rejection counter (how many session families are stopped; an unreadable file);
- a persisted autoaccept (``session.permissions`` in ``~/.config/opencode/cli.json``) or an
  OpenCode process started with ``--auto``: both make the human's approval instant, and the
  dwell check then refuses every use;
- per OpenCode server: would the broker refuse its environment (``E-B-POLLUTED``) or its SSH agent
  (``E-B-NOAGENT``);
- an ``origin`` over HTTPS in the working repository (the broker pushes over SSH only; `carter push`
  takes HTTPS);
- tools the broker runs with the human's credentials that someone other than root could replace
  (``git``, ``gh``, the ``ssh_bin_dir``): a WARN.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path

from carter.broker import audit, counter, env
from carter.checkitems import Item
from carter.guard import consent
from carter.guard.state import GuardState
from carter.identity.errors import (
    E_B_DWELL,
    E_B_HTTPS,
    E_B_NOAGENT,
    E_B_POLLUTED,
    E_B_REJECTED,
    IdentityError,
)
from carter.install.paths import headless_profile_path, isolation_path, run_dir

OPENCODE_CLI_CONFIG = Path(".config") / "opencode" / "cli.json"
INSTALL_HINT = "Run `carter guard install`."


def _isolation_plugin(base_dir: Path | None) -> dict | None:
    try:
        doc = json.loads(isolation_path(base_dir).read_text())
        plugin = doc["plugin"]
        return plugin if isinstance(plugin, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def consent_items(state: GuardState, plugin: dict | None) -> list[Item]:
    wanted = consent.broker_wanted(state)
    enabled = bool(plugin and plugin.get("b_enabled") is True)
    if wanted and enabled:
        return [Item("ok", "push tool", "enabled for devops only (isolation.json)")]
    if wanted:
        text = "the push tool is confirmed but isolation.json has it off (no git found?)"
        return [Item("warn", "push tool", text, INSTALL_HINT)]
    if enabled:
        text = "isolation.json enables the push tool but guard state does not have it confirmed"
        return [Item("red", "push tool", text, INSTALL_HINT)]
    if consent.plugin_wanted(state):
        return [
            Item("info", "push tool", "off: confirm it with `carter guard install` (devops only)")
        ]
    return []


def profile_items(state: GuardState, base_dir: Path | None) -> list[Item]:
    if not consent.broker_wanted(state):
        return []
    path = headless_profile_path(base_dir)
    if state.owned_unchanged(path):
        text = "headless profile present (`OPENCODE_CONFIG=` with `opencode run --standalone`)"
        return [Item("ok", "B headless", text)]
    what = "was changed since Carter wrote it" if path.exists() else "is missing"
    return [Item("warn", "B headless", f"{path.name} {what}", INSTALL_HINT)]


def audit_items(base_dir: Path | None) -> list[Item]:
    carter_dir = run_dir(base_dir).parent
    directory = audit.audit_dir(carter_dir)
    if not directory.exists():
        return [Item("info", "B audit", "no decisions recorded yet")]
    out: list[Item] = []
    bad = []
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        bad.append(f"{directory.name}/ is not 0700")
    for path in sorted(directory.glob("*")):
        if path.is_file() and stat.S_IMODE(path.stat().st_mode) != 0o600:
            bad.append(f"{path.name} is not 0600")
    if bad:
        out.append(
            Item("warn", "B audit", "; ".join(bad), "chmod 700 the directory, 600 the files.")
        )
    events = audit.read_b(carter_dir)
    counts = Counter(str(e.get("decision", "?")) for e in events)
    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "none"
    out.append(Item("info", "B audit", f"{len(events)} recent decision(s): {summary}"))
    return out


def counter_items(base_dir: Path | None) -> list[Item]:
    carter_dir = run_dir(base_dir).parent
    if not counter.path(carter_dir).exists():
        return []
    try:
        families, stopped = counter.summary(carter_dir)
    except counter.CounterError as exc:
        text = f"{E_B_REJECTED}: the rejection counter is unreadable ({exc}); the broker refuses"
        return [Item("warn", "B counter", text, "Run `carter guard status --reset-b`.")]
    if stopped:
        text = (
            f"{stopped} of {families} session famil(ies) stopped after "
            f"{counter.MAX_REJECTIONS} rejections"
        )
        return [
            Item("warn", "B counter", text, "A new session, or `carter guard status --reset-b`.")
        ]
    return [
        Item("info", "B counter", f"{families} session famil(ies) with rejections, none stopped")
    ]


def autoaccept_items(base_dir: Path | None, auto_pids: Callable[[], list[int]]) -> list[Item]:
    """A persisted autoaccept or a ``--auto`` process: the dwell check refuses every use."""
    out: list[Item] = []
    config = (Path.home() if base_dir is None else base_dir) / OPENCODE_CLI_CONFIG
    try:
        mode = json.loads(config.read_text()).get("session", {}).get("permissions")
    except (OSError, ValueError, AttributeError):
        mode = None
    hint = 'Set `session.permissions` back to "prompt" (names only: the file is not shown).'
    if mode == "autoaccept":
        text = (
            "OpenCode is set to auto-accept permissions (session.permissions); "
            f"the broker refuses every use ({E_B_DWELL})"
        )
        out.append(Item("warn", "B approval", text, hint))
    pids = auto_pids()
    if pids:
        text = (
            f"{len(pids)} OpenCode process(es) run with --auto; "
            f"approvals there are instant ({E_B_DWELL})"
        )
        out.append(Item("warn", "B approval", text, "Start OpenCode without --auto."))
    return out


def server_items(
    servers: Callable[[], Mapping[int, Mapping[str, str] | None]],
    home: str,
    tools: env.Tools | None,
) -> list[Item]:
    """For each server: would B accept its environment and its SSH agent?"""
    out: list[Item] = []
    for pid, server in sorted(servers().items()):
        if server is None:
            continue
        names = env.polluted_names(server, home)
        if names:
            text = f"server {pid}: refused with {E_B_POLLUTED} (names only): {', '.join(names)}"
            out.append(
                Item("warn", "B server env", text, "Restart OpenCode from a clean terminal.")
            )
            continue
        if tools is None:
            continue
        try:
            env.agent_socket(server, tools)
        except IdentityError as exc:
            text = f"server {pid}: {E_B_NOAGENT} ({exc.detail})"
            out.append(
                Item(
                    "warn", "B ssh agent", text, "Restart OpenCode from a terminal with your agent."
                )
            )
        else:
            out.append(Item("ok", "B ssh agent", f"server {pid}: SSH_AUTH_SOCK answers"))
    return out


def origin_items(cwd: Path) -> list[Item]:
    try:
        done = subprocess.run(
            ["git", "-C", str(cwd), "-c", "core.fsmonitor=false", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10, check=False, stdin=subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
                 "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"},
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return []
    url = done.stdout.strip().lower()
    if done.returncode == 0 and url.startswith(("https://", "http://")):
        text = (
            f"origin of this repository is HTTPS; the broker pushes over SSH only ({E_B_HTTPS}): "
            "use `carter push`"
        )
        return [Item("warn", "B origin", text)]
    return []


def _unsafe(path: str) -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return False
    return st.st_uid != 0 or bool(st.st_mode & 0o022)


def ownership_items(plugin: dict | None) -> list[Item]:
    """git, gh and the ssh directory run with your credentials: root-owned and not writable by
    others, or a WARN (the install of Carter itself is the same class)."""
    if not plugin or plugin.get("b_enabled") is not True:
        return []
    ssh = str(plugin.get("ssh_bin_dir", ""))
    checks = {"git": str(plugin.get("b_git", "")), "gh": str(plugin.get("b_gh", ""))}
    if ssh:
        checks["ssh_bin_dir"] = ssh
    loose = [name for name, path in checks.items() if path and _unsafe(path)]
    if loose:
        text = (
            f"not root-owned, or writable by others: {', '.join(loose)} "
            "(B runs them with your credentials)"
        )
        return [Item("warn", "push tool", text, "Use the system tools, or accept this residual.")]
    return []


def items(
    state: GuardState,
    base_dir: Path | None,
    cwd: Path,
    *,
    servers: Callable[[], Mapping[int, Mapping[str, str] | None]] | None,
    home: str,
    auto_pids: Callable[[], list[int]],
    ssh_bin_dir: str,
) -> list[Item]:
    if not consent.plugin_wanted(state):
        return []
    plugin = _isolation_plugin(base_dir)
    out = consent_items(state, plugin)
    if not consent.broker_wanted(state) and not (plugin and plugin.get("b_enabled")):
        return out
    out += profile_items(state, base_dir)
    out += audit_items(base_dir)
    out += counter_items(base_dir)
    out += autoaccept_items(base_dir, auto_pids)
    if servers is not None:
        git = str((plugin or {}).get("b_git", ""))
        tools = env.Tools(git, str((plugin or {}).get("b_gh", "")), ssh_bin_dir) if git else None
        out += server_items(servers, home, tools)
    out += origin_items(cwd)
    merged = {**(plugin or {}), "ssh_bin_dir": ssh_bin_dir}
    out += ownership_items(merged)
    return out
