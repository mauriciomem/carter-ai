"""The slice-2a items of ``carter check --host`` (plan 004 steps 29 and 30; RFC App B §3).

Read-only, names only: no environment value, no token, no socket path ever reaches an item.
``gitconfig_first`` runs before anything that calls plain ``git`` or ``opencode``: a malformed
included gitconfig makes every git command fail, and the report must still complete.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from carter import harness
from carter.checkitems import Item, Level
from carter.guard import consent, gitconfig, hooks, plugin, repohooks
from carter.guard.state import GuardState
from carter.identity.errors import E_GIT_OLD, E_OPENCODE_VERSION, registry
from carter.identity.policyset import consent_groups
from carter.identity.rules import pollution_hits
from carter.install import prereqs
from carter.install.paths import carter_gitconfig_path, isolation_path, plugin_dir, run_dir

BAKED = re.compile(r'ISOLATION_SHA256\s*=\s*"([0-9a-f]{64})"')
RESTART = "restart the OpenCode server"
DROPPED_HINT = (
    "OpenCode drops an agent's whole config entry when one of its rules is invalid; fix or "
    "remove `agents.{name}` in {config}, then rerun `carter guard install`"
)
D67 = (
    "shell writes to the global OpenCode config, ~/.gitconfig, ~/.config/git, a repo's "
    ".opencode/, opencode.json and .git/hooks or .git/config are not gated (D67); the edit tool "
    "is denied there"
)


def gitconfig_first(base_dir: Path | None) -> tuple[list[Item], bool]:
    """Is ``~/.carter/gitconfig`` readable by git? (``git config --file`` under ``file_env()``.)"""
    path = carter_gitconfig_path(base_dir)
    if not path.exists():
        return [], True
    try:
        parsed = gitconfig.parses(path)
    except gitconfig.GitError:
        return [
            Item("warn", "git", "git is not available; Carter's gitconfig was not checked")
        ], False
    if parsed:
        return [], True
    text = f"git cannot parse {path}: every git command fails while it is included"
    return [Item("red", "git", text, "Run `carter guard remove`, or delete the file.")], False


def include_items(state: GuardState, base_dir: Path | None) -> list[Item]:
    """The include line: present (OK), missing (RED + the exact line), dotfiles (WARN)."""
    if "hooks" not in consent.accepted_groups(state) and state.gitconfig is None:
        return []
    line = gitconfig.include_line(base_dir)
    if state.gitconfig is not None:
        return []  # Carter wrote the line: the 1G item reports it (present, or RED + the line)
    have = gitconfig.manual_include_state(base_dir)
    if have == "present":
        return [Item("ok", "git", "include.path present (added by you, not by Carter)")]
    text = "include.path for Carter's gitconfig is missing: the pre-push hook is inactive"
    return [Item("warn", "git", text + " (dotfile-managed config: add this line there)", line)]


def hook_scope_items(state: GuardState, cwd: Path) -> list[Item]:
    if "hooks" not in consent.accepted_groups(state):
        return []
    rev = int(state.consents.get("hooks", {}).get("rev", 1))
    out: list[Item] = []
    for event in hooks.events_for_rev(rev):
        name = hooks.hook_name(event)
        scope = gitconfig.hook_scopes(cwd, event).get(name)
        if scope == "global":
            out.append(Item("ok", "git", f"{event} hook {name} is active (scope global)"))
            continue
        text = f"{event} hook {name} is not listed by `git hook list` as global"
        out.append(Item("warn", "git", text + (f" (it is {scope})" if scope else "")))
    return out


def file_items(state: GuardState, base_dir: Path | None) -> list[Item]:
    """Plugin, isolation.json, the script and the gitconfig against guard state; and the hash
    baked into the installed plugin against ``isolation.json`` (a mismatch refuses agent shells)."""
    out: list[Item] = []
    iso, index = isolation_path(base_dir), plugin_dir(base_dir) / "index.ts"
    if consent.plugin_wanted(state):
        for path in (index, *(plugin_dir(base_dir) / n for n in plugin.PLUGIN_FILES), iso):
            if not state.owned_unchanged(path):
                what = "was changed since Carter wrote it" if path.exists() else "is missing"
                text = f"{path} {what}"
                out.append(Item("red", "plugin", text, "Run `carter guard install`."))
    if index.exists() and iso.exists():
        baked = BAKED.search(index.read_text(errors="replace"))
        from carter.identity.isolation import sha256_hex

        actual = sha256_hex(iso.read_bytes())
        if baked is None or baked.group(1) != actual:
            text = "isolation.json does not match the hash in the plugin: agent shells are refused"
            out.append(Item("red", "plugin", text, "Run `carter guard install`."))
        else:
            out.append(Item("ok", "plugin", "plugin and isolation.json match (hash)"))
    return out


def g2_items(state: GuardState, base_dir: Path | None) -> list[Item]:
    out: list[Item] = []
    revs = {g.id: g.rev for g in consent_groups()}
    for group in consent.reconsent_pending(state):
        offer = state.offer(group) or {}
        rev = revs[group]
        if offer.get("decision") == "declined":
            when = offer.get("date", "?")
            text = f"{group} rev {rev} declined on {when}; `carter guard install --only {group}` to reconsider"  # noqa: E501
            out.append(Item("info", "consent", text))
        else:
            what = {
                "g2": "the B tool (carter_push for devops)"
                if consent.plugin_wanted(state)
                else "the plugin and the B tools"
            }.get(group, "the new content")
            out.append(
                Item(
                    "info", "consent", f"{group} rev {rev} pending: {what} needs your confirmation"
                )
            )
    iso = isolation_path(base_dir)
    if iso.exists():
        try:
            listed = sorted(json.loads(iso.read_text())["plugin"]["declined_groups"])
        except (ValueError, KeyError, TypeError):
            return out
        if listed != sorted(consent.declined_groups(state)):
            text = "isolation.json lists different declined groups than guard-state.json"
            out.append(Item("warn", "consent", text, "Run `carter guard install`."))
    return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # exists, not ours
        return True
    return True


def status_items(
    state: GuardState, base_dir: Path | None, opencode_version: tuple[int, int, int] | None
) -> list[Item]:
    """One item per OpenCode server that wrote ``run/plugin-status/<pid>.json``."""
    if not consent.plugin_wanted(state):
        return []
    folder = run_dir(base_dir) / "plugin-status"
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    live = []
    for path in files:
        try:
            doc = json.loads(path.read_text())
            pid = int(doc["pid"])
        except (ValueError, KeyError, TypeError, OSError):
            continue
        if _alive(pid):
            live.append((path, doc))
    if not live:
        text = "not loaded yet: start OpenCode and run an agent command"
        return [Item("warn", "plugin", text)]
    out: list[Item] = []
    index = plugin_dir(base_dir) / "index.ts"
    shown = ".".join(map(str, opencode_version)) if opencode_version else None
    for _path, doc in live:
        pid, st = doc["pid"], doc.get("state")
        label = f"server {pid}"
        if st == "passed":
            out.append(Item("ok", "plugin", f"{label}: self-test passed"))
        elif st == "failed":
            why = doc.get("failed_reason")
            text = f"{label}: self-test failed ({why}); all shells are treated as agent shells"
            out.append(Item("red", "plugin", text, f"See {E_OPENCODE_VERSION}; {RESTART}."))
        else:
            out.append(
                Item("warn", "plugin", f"{label}: self-test unproven (run an agent command)")
            )
        if shown and doc.get("opencode_version") not in (None, shown):
            out.append(
                Item("warn", "plugin", f"{label}: started on another OpenCode version", RESTART)
            )
        try:
            since = datetime.fromisoformat(str(doc["since"]).replace("Z", "+00:00")).timestamp()
            if index.exists() and since < index.stat().st_mtime:
                out.append(
                    Item(
                        "warn", "plugin", f"{label}: status is older than the plugin file", RESTART
                    )
                )
        except (ValueError, KeyError):
            pass
    return out


def foreign_plugin_items(base_dir: Path | None, cwd: Path) -> list[Item]:
    """Plugin code Carter did not write, by name (D66): global ``plugin/`` and ``plugins/``."""
    names = plugin.unexpected_files(base_dir)
    for sub in ("plugin", "plugins"):
        folder = cwd / ".opencode" / sub
        if folder.is_dir():
            names += [f"{cwd.name}/.opencode/{sub}/{p.name}" for p in sorted(folder.iterdir())]
    if not names:
        return []
    return [Item("warn", "plugin files", f"not written by Carter: {', '.join(names)}")]


def repo_items(
    state: GuardState,
    base_dir: Path | None,
    cwd: Path,
    workspaces: list[str],
    tier: str,
    mode: str | None,
) -> list[Item]:
    """Per-repo coverage on git < 2.54: WARN, FAIL only when T2 is configured."""
    if mode != "no-config-hooks":
        return []
    events = hooks.events_for_rev(int(state.consents.get("repo_hooks", {}).get("rev", 1)))
    found = repohooks.scan(repohooks.repos_in_scope(cwd, workspaces), state, base_dir, events)
    bad: Level = "red" if repohooks.verdict(found, tier) == "fail" else "warn"
    entry = registry()[E_GIT_OLD]
    out = [Item("info", "git", f"{E_GIT_OLD}: {entry.message}")]
    for s in found:
        level: Level = "ok" if s.state == "guarded" else bad
        out.append(Item(level, "git", s.line(), s.snippet.split("\n")[0]))
    return out


def pollution_items(
    servers: Callable[[], Mapping[int, Mapping[str, str] | None]], home: str
) -> list[Item]:
    """Names in the OpenCode server's environment that break isolation (values never read out)."""
    envs = servers()
    if not envs:
        return [Item("info", "server env", "no running OpenCode server found")]
    out: list[Item] = []
    for pid, env in sorted(envs.items()):
        if env is None:
            out.append(Item("info", "server env", f"cannot read the environment of server {pid}"))
            continue
        hits = pollution_hits(env, home=home)
        tokens = [n for n in ("GH_TOKEN", "GITHUB_TOKEN") if n in env]
        if hits:
            text = (
                f"server {pid} started from a polluted environment (names only): {', '.join(hits)}"
            )
            out.append(Item("warn", "server env", text, "Restart OpenCode from a clean terminal."))
        if tokens:
            out.append(
                Item("warn", "server env", f"server {pid} has {', '.join(tokens)} set (names only)")
            )
        if not hits and not tokens:
            out.append(Item("ok", "server env", f"server {pid}: no pollution"))
    return out


def agent_items(
    state: GuardState,
    agents_reader: Callable[[], list[dict]],
    loaded: Mapping[str, object] | None,
    config_path: str,
) -> list[Item]:
    """Each agent's effective ``carter_push`` rule from ``opencode debug agents``."""
    if not consent.accepted_groups(state) or "g2" not in consent.accepted_groups(state):
        return []
    try:
        agents = agents_reader()
    except harness.DebugConfigError as exc:
        return [Item("warn", "per-agent denies", f"cannot read `opencode debug agents` ({exc})")]
    out: list[Item] = []
    for name, action in harness.agent_deny_gaps(agents):
        text = f"agent {name}: {action} is not denied in `opencode debug agents`"
        out.append(Item("red", "per-agent denies", text, "Run `carter guard install`."))
    known = loaded.get("agents") if isinstance(loaded, Mapping) else None
    if isinstance(known, Mapping):
        for rec in state.owned_permissions():
            if rec["agent"] not in known:
                hint = DROPPED_HINT.format(name=rec["agent"], config=config_path)
                text = f"agent {rec['agent']}: OpenCode dropped its config entry"
                out.append(Item("red", "per-agent denies", text, hint))
    if not out:
        out.append(
            Item("ok", "per-agent denies", f"{len(agents)} agent(s) carry the carter_* denies")
        )
    return out


def version_items(opencode: tuple[int, int, int] | None, git: tuple[int, int] | None) -> list[Item]:
    out: list[Item] = []
    if opencode is not None:
        band = prereqs.version_band(opencode)
        shown = ".".join(map(str, opencode))
        if band == "too-old":
            out.append(
                Item("red", "opencode", f"{shown} is older than 2.1: Carter needs 2.1 or newer")
            )
        elif band in ("untested-low", "above"):
            text = f"{E_OPENCODE_VERSION}: G2 untested on {shown}; relying on the plugin self-test"
            out.append(Item("warn", "opencode", text))
        else:
            out.append(Item("ok", "opencode", f"{shown} (tested)"))
    if git is not None and git < repohooks.MIN_CONFIG_HOOKS:
        entry = registry()[E_GIT_OLD]
        out.append(Item("warn", "git", f"{E_GIT_OLD}: {entry.message}"))
    return out


def residual_items() -> list[Item]:
    return [Item("info", "residual", D67)]
