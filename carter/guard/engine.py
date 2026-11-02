"""``carter guard install`` / ``remove``: the single owner of G2 artifacts (RFC-0007 C.6.2).

1G scope: policies, per-agent permissions, Carter's gitconfig + include line (machinery only,
no entries yet) and guard state. No plugin, ``isolation.json`` or hooks (slice 2a).

Order and atomicity. Consent is resolved in memory first. Policies and the per-agent denies
go to the OpenCode config in ONE verified write (rolled back on any loss); the git part
follows; guard state is saved **last**. If the git part fails, the config is restored from
the backup and the state file keeps its previous content. Nothing here prompts through
click: callers pass ``confirm`` and ``echo`` so this module is testable and click-free.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from carter import harness
from carter.guard import configwrite, consent, gitconfig, optout, policies
from carter.guard.state import GuardState, load_or_empty_readonly, quarantine_corrupt, save
from carter.identity import ConfigError, load_identity
from carter.identity.errors import E_STATE_INVALID, IdentityError
from carter.identity.policyset import ConsentGroup, Statement, consent_groups, policy_statements
from carter.install.atomic import atomic_write_bytes
from carter.install.paths import backups_dir, guard_state_path

Echo = Callable[[str], None]
Confirm = Callable[[str], bool]

INTERIM_NOTE = (
    "Interim: plugin and isolation are not installed; literal denies only. They are a speed "
    "bump, not a boundary, until slice 2a (the gate and shell isolation) lands."
)
GIT_NOT_NEEDED = "include.path: not needed yet (no Carter git keys; slice 2a)"
PAT_KEPT = (
    "`~/.carter/secrets/gh-read.token` kept; delete it and revoke the token on GitHub if unused"
)
# Files a later slice installs; removal deletes them only if recorded and unchanged.
KNOWN_EXTRA_FILES = ("isolation.json", "opencode-headless.json", "run/plugin-status.json")


class GuardAbort(Exception):
    """The human said no (or a precondition failed); nothing was changed. Exit code 1."""


def format_error(exc: BaseException) -> str | None:
    """``Error:`` text for the failures guard commands expect (F9); ``None`` for anything else."""
    if isinstance(exc, IdentityError):
        extra = f" ({exc.detail})" if exc.detail else ""
        return f"{exc.code}: {exc}{extra}"
    expected = (policies.PolicyWriteError, GuardAbort, gitconfig.GitError, harness.DebugConfigError)
    return str(exc) if isinstance(exc, expected) else None


def _stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")


def builtin_agents() -> list[str]:
    """Agents OpenCode knows that are not Carter's (the built-ins and the user's own)."""
    try:
        ids = harness.read_agent_ids()
    except harness.DebugConfigError as exc:
        raise policies.PolicyWriteError(
            f"cannot list OpenCode's agents ({exc}); nothing was written"
        ) from exc
    return [i for i in ids if not i.startswith("carter-")]


def _load_state(
    base_dir: Path | None, *, dry_run: bool, assume_yes: bool, confirm: Confirm, echo: Echo
) -> GuardState:
    path = guard_state_path(base_dir)
    read = load_or_empty_readonly(path)
    if read.status == "newer":
        raise IdentityError(E_STATE_INVALID, detail=read.detail)
    if read.status == "corrupt":
        echo(f"guard state {path} is unreadable ({read.detail}).")
        if dry_run:
            echo("A real install would move it aside and start fresh (nothing is written now).")
        elif assume_yes or confirm(
            "Move it aside and start a new one? Carter forgets what it owns."
        ):
            echo(f"Moved to {quarantine_corrupt(path, now=_stamp())}")
        else:
            raise GuardAbort("Left the unreadable guard state alone; nothing was changed.")
    return read.state


def _live_ids() -> list[str]:
    return [g.id for g in consent_groups() if g.live]


def _active_optouts(
    state: GuardState, *, assume_yes: bool, interactive: bool, confirm: Confirm, echo: Echo
) -> list[Statement]:
    """D52: list every active opt-out; ask unless ``--yes`` (which skips only the question)."""
    if consent.CONFIG_EDIT not in consent.accepted_groups(state):
        return []
    try:
        found = optout.active_optouts(load_identity())
    except ConfigError:
        echo("config.toml is invalid; D52 opt-outs not applied.")
        return []
    if found.workspaces or found.refused:
        echo("Active D52 opt-outs (agents may edit these project files):")
        for line in optout.describe(found):
            echo(line)
    if not found.workspaces:
        return []
    if not assume_yes and (not interactive or not confirm("Apply these opt-outs?")):
        echo("Opt-outs not applied.")
        return []
    return found.statements()


def _show_diff(res: policies.ApplyResult, wanted: list[Statement], echo: Echo) -> None:
    by_id = {s.id: s for s in wanted}
    for ident in res.removed:
        echo(f"  - {ident}")
    for ident in res.added:
        s = by_id[ident]
        echo(f"  + {ident:<34} {s.resource}  [{s.effect}]")
    kept = len(wanted) - len(res.added) - len(res.preexisting)
    echo(f"  = {max(kept, 0)} statement(s) unchanged, {len(res.preexisting)} already yours")
    for label in res.perms.added:
        echo(f"  + per-agent deny {label}")
    for label in res.perms.removed:
        echo(f"  - per-agent deny {label}")
    for text in res.perms.warnings + res.warnings:
        echo(f"  ⚠ {text}")


def _undo_git(base_dir: Path | None, before: GuardState, after: GuardState) -> None:
    """Remove only what the failed git step itself created (never earlier ownership)."""
    new = GuardState()
    if after.gitconfig and not before.gitconfig:
        new.gitconfig = after.gitconfig
    known = {f["path"] for f in before.files}
    new.files = [f for f in after.files if f["path"] not in known]
    new.git_config = [r for r in after.git_config if r not in before.git_config]
    gitconfig.remove_all(base_dir, new)


def _git_step(base_dir: Path | None, state: GuardState, echo: Echo, *, dry_run: bool) -> None:
    entries = gitconfig.carter_git_entries()
    if not entries:
        echo(GIT_NOT_NEEDED)
        return
    mode = gitconfig.probe_scope()
    echo(f"git config: {len(entries)} key(s), mode {mode}")
    if dry_run:
        return
    res = gitconfig.apply_keys(entries, mode=mode, base_dir=base_dir, state=state)
    if res.include and res.include.status == "manual":
        echo(f"⚠ {res.include.note}\n    {res.include.line}")
    if res.direct:
        for line in res.direct.manual:
            echo(f"⚠ add by hand: {line}")
        for key in res.direct.conflicts:
            echo(f"⚠ kept your value for {key}")
    for key in res.needs_repo_hooks:
        echo(f"⚠ {key}: git < 2.54 needs the per-repo fallback (slice 2a)")


def install(
    *,
    base_dir: Path | None,
    only: list[str] | None,
    assume_yes: bool,
    interactive: bool,
    dry_run: bool,
    print_policies: bool,
    echo: Echo,
    confirm: Confirm,
    reader: configwrite.Reader | None = None,
) -> int:
    """Run ``carter guard install``. Returns the exit code (0 also for a skipped install)."""
    home = str(Path.home())
    groups = {g.id: g for g in consent_groups()}
    if print_policies:
        chosen = [g for g in (only or _live_ids()) if groups[g].live]
        sts = list(policy_statements(chosen, home=home))
        if consent.CONFIG_EDIT in chosen:
            sts += optout.active_optouts(load_identity()).statements()
        echo(policies.render_snippet(sts).rstrip("\n"))
        return 0

    state = _load_state(
        base_dir, dry_run=dry_run, assume_yes=assume_yes, confirm=confirm, echo=echo
    )
    today = datetime.now(UTC).date().isoformat()
    if dry_run:
        return _dry_run(base_dir, state, only, home, echo, today)

    def ask(group: ConsentGroup) -> bool:
        return confirm(f"{group.id}: {group.effect}\n  Install this group?")

    plan = consent.resolve_consents(
        state, only=only, assume_yes=assume_yes, interactive=interactive, ask=ask
    )
    for note in plan.notices():
        echo(note)
    if plan.skipped:
        return 0
    consent.record(state, plan, today=today)
    for name in plan.declined:
        echo(f"Declined: {name} (listed as a residual by `carter guard status`).")
    optouts = _active_optouts(
        state, assume_yes=assume_yes, interactive=interactive, confirm=confirm, echo=echo
    )
    wanted = consent.desired_statements(state, home=home, optouts=optouts)
    agents = builtin_agents() if "g2" in consent.accepted_groups(state) else []
    before = copy.deepcopy(state)
    state_path = guard_state_path(base_dir)
    previous = state_path.read_bytes() if state_path.exists() else None
    res = policies.apply(
        base_dir, state, wanted, agents=agents,
        backup_root=backups_dir(base_dir) / _stamp(), reader=reader,
    )  # fmt: skip
    try:
        echo(f"OpenCode config: {res.target}" + ("" if res.changed else " (already up to date)"))
        _show_diff(res, wanted, echo)
        # Ownership is recorded the moment the config holds our statements, so a process
        # killed during the git step leaves a consistent pair, never orphaned policies.
        if state != GuardState() or state_path.exists():
            save(state, state_path)
        _git_step(base_dir, state, echo, dry_run=False)
        if state != GuardState() or state_path.exists():
            save(state, state_path)
    except BaseException:
        if res.tx is not None and res.target is not None:
            configwrite.restore(res.target, res.tx)
        _undo_git(base_dir, before, state)
        if previous is None:
            state_path.unlink(missing_ok=True)
        else:
            atomic_write_bytes(state_path, previous)
        raise
    echo(INTERIM_NOTE)
    return 0


def _dry_run(
    base_dir: Path | None, state: GuardState, only: list[str] | None, home: str, echo: Echo,
    today: str,
) -> int:  # fmt: skip
    """Show what a real install would do if every undecided group in scope were accepted."""
    echo("carter guard install (dry run: nothing is written)")
    preview = copy.deepcopy(state)
    groups = {g.id: g for g in consent_groups()}
    scope = only if only is not None else [g.id for g in consent_groups()]
    echo("Groups:")
    for name in scope:
        group = groups[name]
        prior = state.consents.get(name, {}).get("decision")
        if not group.live:
            echo(f"  {name:<18} nothing to install in this version")
            continue
        if prior == "declined" and not (only and name in only):
            echo(f"  {name:<18} declined earlier (stays declined)")
            continue
        status = prior or "would ask"
        echo(f"  {name:<18} {status}: {group.effect}")
        preview.consent(name, "accepted", today)
    optouts = (
        optout.active_optouts(load_identity()).statements()
        if consent.CONFIG_EDIT in consent.accepted_groups(preview)
        else []
    )
    wanted = consent.desired_statements(preview, home=home, optouts=optouts)
    try:
        agents = builtin_agents() if "g2" in consent.accepted_groups(preview) else []
    except policies.PolicyWriteError as exc:
        echo(f"  ⚠ {exc}")
        agents = []
    res = policies.apply(
        base_dir, preview, wanted, agents=agents, backup_root=backups_dir(base_dir), dry_run=True
    )
    echo(f"OpenCode config: {res.target}" + ("" if res.changed else " (already up to date)"))
    _show_diff(res, wanted, echo)
    if agents:
        echo(f"  per-agent denies for built-in agents: {', '.join(agents)}")
    _git_step(base_dir, preview, echo, dry_run=True)
    verb = "updated" if state.consents else "created"
    echo(f"Guard state: {guard_state_path(base_dir)} (would be {verb})")
    echo(INTERIM_NOTE)
    return 0


# -- remove ---------------------------------------------------------------------------------


def _known_extra_files(base_dir: Path | None, state: GuardState, echo: Echo) -> None:
    """Delete recorded, unchanged files Carter installed; keep and report the rest."""
    root = guard_state_path(base_dir).parent
    for rel in KNOWN_EXTRA_FILES:
        path = root / rel
        if path.exists() and not state.owned_unchanged(path):
            echo(f"  kept {path}: not recorded as Carter's, or changed since")
    for rec in list(state.files):
        path = Path(rec["path"])
        if state.owned_unchanged(path):
            path.unlink()
            echo(f"  removed {path}")
        elif path.exists():
            echo(f"  kept {path}: changed since Carter wrote it")
        state.forget_file(path)


def remove(
    *,
    base_dir: Path | None,
    only: list[str] | None,
    assume_yes: bool,
    interactive: bool,
    dry_run: bool,
    echo: Echo,
    confirm: Confirm,
    reader: configwrite.Reader | None = None,
) -> int:
    """Run ``carter guard remove``: policies and permissions, then git config, then state."""
    path = guard_state_path(base_dir)
    read = load_or_empty_readonly(path)
    if read.status == "newer":
        raise IdentityError(E_STATE_INVALID, detail=read.detail)
    if read.status == "corrupt":
        raise IdentityError(E_STATE_INVALID, detail=read.detail)
    state = read.state
    if read.status == "absent" or state == GuardState():
        echo("Nothing to remove: Carter has no guard state here.")
        return 0
    scoped = only is not None
    if dry_run:
        echo("carter guard remove (dry run: nothing is written)")
    elif not assume_yes and not (interactive and confirm("Remove what Carter installed?")):
        raise GuardAbort("Nothing was removed.")
    home = str(Path.home())
    root = backups_dir(base_dir) / _stamp()
    if scoped:
        target = copy.deepcopy(state) if dry_run else state
        for name in only or []:
            target.consents.pop(name, None)
        wanted = consent.desired_statements(target, home=home)
        agents = builtin_agents() if "g2" in consent.accepted_groups(target) else []
        res = policies.apply(
            base_dir,
            target,
            wanted,
            agents=agents,
            backup_root=root,
            dry_run=dry_run,
            reader=reader,
        )
        echo(f"OpenCode config: {res.target}")
        _show_diff(res, wanted, echo)
        if not dry_run:
            save(target, path)
        return 0
    rem = policies.remove(base_dir, state, backup_root=root, dry_run=dry_run, reader=reader)
    for ident in rem.removed + rem.perms.removed:
        echo(f"  - {ident}")
    for ident in rem.kept_edited + rem.perms.kept_edited:
        echo(f"  kept {ident}: edited since Carter wrote it")
    if dry_run:
        echo("  (git config, Carter's files and the guard state would be removed too)")
        return 0
    git = gitconfig.remove_all(base_dir, state)
    for result in [git.include] if git.include else []:
        if result.status == "manual":
            echo(f"⚠ {result.note}\n    {result.line}")
        elif result.status == "absent":
            echo(f"  {result.note}")
    for name in git.files.removed:
        echo(f"  removed {name}")
    for name in git.files.kept:
        echo(f"  kept {name}: edited since Carter wrote it")
    _known_extra_files(base_dir, state, echo)
    if (path.parent / "secrets" / "gh-read.token").exists():
        echo(PAT_KEPT)
    path.unlink(missing_ok=True)
    echo("Removed guard state. (state/audit/ is kept.)")
    return 0
