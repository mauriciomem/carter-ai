"""``carter guard status``: a read-only report of what Carter owns and whether it is intact.

Never writes, works with an absent or corrupt guard state (it reports that), and never
prints provider settings: ``opencode debug config`` is compared in memory only. Per statement:
an invalid statement is dropped alone by OpenCode, so one missing line is one missing line.
``carter check --host`` (step 21) builds on the same pieces.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from carter import harness
from carter.guard import consent, gitconfig, hooks
from carter.guard.configwrite import Reader, missing_statements, target_path
from carter.guard.state import GuardState, load_or_empty_readonly
from carter.identity.policyset import Statement, consent_groups
from carter.install.jsonc import _load_jsonc
from carter.install.paths import guard_state_path

Echo = Callable[[str], None]
GIT_NOT_NEEDED = "include.path: not needed (no Carter git keys are enabled)"


def _consents(state: GuardState, echo: Echo) -> None:
    echo("Consents:")
    reserved = []
    for group in consent_groups():
        if not group.live:
            reserved.append(group.id)
            continue
        rec = state.consents.get(group.id)
        if rec is None:
            echo(f"  {group.id:<18} not decided yet")
        elif rec["decision"] == "accepted":
            echo(f"  {group.id:<18} accepted {rec['date']}")
        else:
            echo(f"  {group.id:<18} declined {rec['date']}  (residual: not installed)")
    echo(f"  {', '.join(reserved)}: reserved, nothing to install in this version")


def _policies(state: GuardState, reader: Reader | None, echo: Echo) -> None:
    recorded = state.opencode_policies
    echo(f"OpenCode config: {state.opencode_config or target_path(None)}")
    if not recorded:
        echo("  no policies recorded")
        return
    wanted = [Statement(p["id"], "", p["action"], p["resource"], p["effect"], "") for p in recorded]
    try:
        loaded = (reader or harness.read_debug_config)()
    except harness.DebugConfigError as exc:
        echo(f"  cannot verify {len(recorded)} statement(s): {exc}")
        return
    missing = {s.id for s in missing_statements(loaded, wanted)}
    for rec in recorded:
        mark = "MISSING" if rec["id"] in missing else "loaded"
        note = " (already yours)" if rec["preexisting"] else ""
        echo(f"  {mark:<8} {rec['id']}{note}")
    if missing:
        echo("  A broken config drops all policies and providers: re-run `carter guard install`.")


def _permissions(state: GuardState, echo: Echo) -> None:
    if not state.agent_permissions:
        return
    config = _load_jsonc(target_path(None)) if target_path(None).exists() else None
    agents = sorted({r["agent"] for r in state.agent_permissions})
    echo(f"Per-agent denies recorded for: {', '.join(agents)}")
    if config is None:
        echo("  cannot read the OpenCode config to confirm them")


def _files(state: GuardState, echo: Echo) -> None:
    for rec in state.files:
        path = Path(rec["path"])
        ok = state.owned_unchanged(path)
        echo(f"  {'ok     ' if ok else 'CHANGED' if path.exists() else 'MISSING'} {path}")


def _git(state: GuardState, base_dir: Path | None, echo: Echo) -> None:
    rec = state.gitconfig
    if (
        rec is None
        and "hooks" in consent.accepted_groups(state)
        and Path(hooks.script_path(base_dir)).exists()
    ):
        have = gitconfig.manual_include_state(base_dir)
        if have == "present":
            echo("include.path: present (you added it; Carter did not write your global config)")
        else:
            echo(
                "include.path: NOT in your global git config: the pre-push hook is inactive "
                f"until you run\n    {gitconfig.include_line(base_dir)}"
            )
    elif rec is None and not state.git_config:
        echo(GIT_NOT_NEEDED)
        return
    if rec is not None:
        cfg = Path(rec["file"])
        present = cfg.exists() and gitconfig.has_include_line(cfg, rec["value"])
        echo(f"include.path: {'present' if present else 'MISSING'} in {cfg}")
        carter_file = Path(rec["value"])
        broken = carter_file.exists() and not gitconfig.parses(carter_file)
        if broken:
            echo(
                f"INVALID {carter_file}: git cannot parse it, and while the include line is "
                "present every git command fails. Fix the file, or run `carter guard remove`."
            )
    for r in state.git_config:
        echo(f"git key {r['key']} recorded in {r['file']}")
    for hook in state.repo_hooks:
        path = Path(hook["path"])
        mark = (
            "ok     "
            if state.repo_hook_unchanged(path)
            else "CHANGED"
            if path.exists()
            else "MISSING"
        )
        echo(f"repo hook {mark} {path}")


def report(base_dir: Path | None, echo: Echo, *, reader: Reader | None = None) -> None:
    path = guard_state_path(base_dir)
    read = load_or_empty_readonly(path)
    label = {"absent": "absent (nothing installed)", "ok": "ok"}.get(read.status)
    echo(f"Guard state: {path}: {label or read.status.upper() + ': ' + read.detail}")
    if read.status in ("corrupt", "newer"):
        echo("  Carter does not rebuild it: fix or move the file, then run `carter guard install`.")
        return
    state = read.state
    _consents(state, echo)
    _policies(state, reader, echo)
    _permissions(state, echo)
    if state.files:
        echo("Files:")
        _files(state, echo)
    _git(state, base_dir, echo)
    if consent.plugin_wanted(state):
        echo("Plugin: installed (g2 revision 2); `carter check --host` says if OpenCode loaded it")
        echo(
            "Isolation: isolation.json is rendered; agent shells are isolated once the plugin loads"
        )
    else:
        pending = "g2" in consent.reconsent_pending(state)
        echo(
            "Plugin: not installed"
            + (" (needs your confirmation: `carter guard install`)" if pending else "")
        )
        echo("Isolation: not installed; agent shells still inherit your SSH agent and gh")
    accepted = ", ".join(consent.accepted_groups(state)) or "none"
    echo(f"Active groups: {accepted}")
