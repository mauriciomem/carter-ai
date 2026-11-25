"""``carter guard status``: a read-only report of what Carter owns and whether it is intact.

Never writes, works with an absent or corrupt guard state (it reports that), and never
prints provider settings: ``opencode debug config`` is compared in memory only. Per statement:
an invalid statement is dropped alone by OpenCode, so one missing line is one missing line.
``carter check --host`` builds on the same pieces.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from carter.guard import agent_rules, consent, gitconfig, hooks
from carter.guard.configwrite import target_path
from carter.guard.state import GuardState, load_or_empty_readonly
from carter.home import tilde
from carter.identity.policyset import consent_groups
from carter.install.jsonc import _load_jsonc
from carter.install.paths import guard_state_path

Echo = Callable[[str], None]
GIT_NOT_NEEDED = "include.path: not needed (no Carter git keys are enabled)"


def _consents(state: GuardState, echo: Echo) -> None:
    echo("Consents:")
    for group in consent_groups():
        rec = state.consents.get(group.id)
        if rec is None:
            how = "optional, not installed" if group.optional else "not decided yet"
            echo(f"  {group.id:<16} {how}")
        elif rec["decision"] == "accepted":
            echo(f"  {group.id:<16} accepted {rec['date']}")
        elif group.optional:
            echo(f"  {group.id:<16} declined {rec['date']}  (optional)")
        else:
            echo(f"  {group.id:<16} declined {rec['date']}  (see: carter guard --help)")


def _policies(state: GuardState, base_dir: Path | None, echo: Echo) -> None:
    """G2's rules live in the Carter agent files; the OpenCode config holds no policies."""
    echo(f"OpenCode config: {tilde(state.opencode_config or target_path(base_dir))}")
    if state.opencode_policies:
        echo(f"  {len(state.opencode_policies)} old global policies still recorded")
        echo("→ run: carter guard install")
    else:
        echo("  no global policies (rules live in the Carter agent files)")
    current, drifted = agent_rules.agent_file_state(base_dir)
    if current:
        echo(f"  Carter agent files carrying the guard rules: {len(current)}")
    for name in drifted:
        echo(f"  CHANGED {name}: permissions differ from Carter's")


def _permissions(state: GuardState, echo: Echo) -> None:
    if not state.agent_permissions:
        return
    config = _load_jsonc(target_path(None)) if target_path(None).exists() else None
    agents = sorted({r["agent"] for r in state.agent_permissions})
    echo(f"Agents with `carter_push` denied: {', '.join(agents)}")
    if config is None:
        echo("  cannot read the OpenCode config to confirm them")


def _files(state: GuardState, echo: Echo) -> None:
    for rec in state.files:
        path = Path(rec["path"])
        ok = state.owned_unchanged(path)
        echo(f"  {'ok     ' if ok else 'CHANGED' if path.exists() else 'MISSING'} {tilde(path)}")


def _git(state: GuardState, base_dir: Path | None, echo: Echo) -> None:
    rec = state.gitconfig
    if (
        rec is None
        and "hooks" in consent.accepted_groups(state)
        and Path(hooks.script_path(base_dir)).exists()
    ):
        have = gitconfig.manual_include_state(base_dir)
        if have == "present":
            echo("include.path: present (you added it)")
        else:
            echo("include.path: NOT in ~/.gitconfig: hooks inactive")
            echo(gitconfig.SEE_INSTALL)
    elif rec is None and not state.git_config:
        echo(GIT_NOT_NEEDED)
        return
    if rec is not None:
        cfg = Path(rec["file"])
        present = cfg.exists() and gitconfig.has_include_line(cfg, rec["value"])
        echo(f"include.path: {'present' if present else 'MISSING'} in {tilde(cfg)}")
        carter_file = Path(rec["value"])
        broken = carter_file.exists() and not gitconfig.parses(carter_file)
        if broken:
            echo(f"INVALID {tilde(carter_file)}: git cannot parse it")
            echo("→ fix the file, or run: carter guard remove")
    for r in state.git_config:
        echo(f"git key {r['key']} recorded in {tilde(r['file'])}")
    for hook in state.repo_hooks:
        path = Path(hook["path"])
        mark = (
            "ok     "
            if state.repo_hook_unchanged(path)
            else "CHANGED"
            if path.exists()
            else "MISSING"
        )
        echo(f"repo hook {mark} {tilde(path)}")


def report(base_dir: Path | None, echo: Echo) -> None:
    path = guard_state_path(base_dir)
    read = load_or_empty_readonly(path)
    label = {"absent": "absent (nothing installed)", "ok": "ok"}.get(read.status)
    echo(f"Guard state: {tilde(path)}: {label or read.status.upper() + ': ' + read.detail}")
    if read.status in ("corrupt", "newer"):
        echo("  Carter never rebuilds it: fix or move the file")
        return
    state = read.state
    _consents(state, echo)
    _policies(state, base_dir, echo)
    _permissions(state, echo)
    if state.files:
        echo("Files:")
        _files(state, echo)
    _git(state, base_dir, echo)
    if consent.plugin_wanted(state):
        echo("Plugin: installed (is it loaded? carter check --host)")
        echo("Isolation: written; active once the plugin loads")
    else:
        pending = "g2" in consent.reconsent_pending(state)
        echo("Plugin: not installed" + (" (confirm: carter guard install)" if pending else ""))
        echo("Isolation: not installed; shells keep your SSH agent")
    accepted = ", ".join(consent.accepted_groups(state)) or "none"
    echo(f"Active groups: {accepted}")
