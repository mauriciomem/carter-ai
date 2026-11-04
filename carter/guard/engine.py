"""``carter guard install`` / ``remove``: the single owner of G2 artifacts (RFC-0007 C.6.2).

Scope so far: policies, per-agent permissions, guard state, and (2a step 24-25) the ``hooks``
group: ``~/.carter/hooks/carter-guard``, the ``pre-push`` entries in ``~/.carter/gitconfig`` and
the include line, or on git < 2.54 the ``repo_hooks`` fallback. No plugin yet (step 26).

Order and atomicity. Consent is resolved in memory first. Policies and the per-agent denies
go to the OpenCode config in ONE verified write (rolled back on any loss); the git part
follows; guard state is saved **last**. If the git part fails, the config is restored from
the backup and the state file keeps its previous content. Nothing here prompts through
click: callers pass ``confirm`` and ``echo`` so this module is testable and click-free.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from carter import harness
from carter.guard import (
    alias,
    configwrite,
    consent,
    gitconfig,
    hooks,
    mirror_io,
    optout,
    plugin,
    policies,
    repohooks,
)
from carter.guard.state import GuardState, load_or_empty_readonly, quarantine_corrupt, save
from carter.identity import ConfigError, load_identity
from carter.identity.errors import E_GIT_OLD, E_STATE_INVALID, IdentityError, registry
from carter.identity.policyset import ConsentGroup, Statement, consent_groups, policy_statements
from carter.install.atomic import atomic_write_bytes
from carter.install.paths import backups_dir, carter_gitconfig_path, guard_state_path

Echo = Callable[[str], None]
Confirm = Callable[..., bool]

INTERIM_NOTE = (
    "Interim: plugin and isolation are not installed; literal denies only. They are a speed "
    "bump, not a boundary, until the plugin is confirmed (`g2` revision 2)."
)
GIT_NOT_NEEDED = "include.path: not needed (no Carter git keys are enabled)"
PAT_KEPT = (
    "`~/.carter/secrets/gh-read.token` kept; delete it and revoke the token on GitHub if unused"
)
# Files a later slice installs; removal deletes them only if recorded and unchanged.
KNOWN_EXTRA_FILES = ("opencode-headless.json",)


class GuardAbort(Exception):
    """The human said no (or a precondition failed); nothing was changed. Exit code 1."""


def format_error(exc: BaseException) -> str | None:
    """``Error:`` text for the failures guard commands expect (F9); ``None`` for anything else."""
    if isinstance(exc, IdentityError):
        extra = f" ({exc.detail})" if exc.detail else ""
        return f"{exc.code}: {exc}{extra}"
    expected = (
        policies.PolicyWriteError,
        GuardAbort,
        gitconfig.GitError,
        harness.DebugConfigError,
        plugin.PluginInstallError,
    )
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
    for rec in new.files:  # the guard script and the template hook, written by this run
        Path(rec["path"]).unlink(missing_ok=True)
    for rec in after.repo_hooks:
        if rec not in before.repo_hooks:
            Path(rec["path"]).unlink(missing_ok=True)
    if not any(f["path"].endswith("isolation.json") for f in before.files):
        plugin.cleanup_dirs(base_dir)


def _availability(echo: Echo) -> tuple[gitconfig.Mode | None, dict[str, str]]:
    """What this git can do (D61 probe) and which hook groups therefore make no sense here.

    ``hooks`` needs git >= 2.54 (E-GIT-OLD otherwise: ``repo_hooks`` is offered instead);
    ``repo_hooks`` is for older git only. No consent is asked for nothing (G10)."""
    try:
        mode = gitconfig.probe_scope()
    except gitconfig.GitError as exc:
        why = f"git is not usable here ({exc}); no hook was installed"
        return None, {"hooks": why, "repo_hooks": why}
    if mode == "no-config-hooks":
        entry = registry()[E_GIT_OLD]
        return mode, {"hooks": f"{entry.code}: {entry.message}"}
    return mode, {
        "repo_hooks": "not needed: this git runs the config hook of `hooks` in every repo"
    }


def _remove_script(base_dir: Path | None, state: GuardState, echo: Echo) -> None:
    path = hooks.script_path(base_dir)
    if state.owned_unchanged(path):
        path.unlink()
        echo(f"  removed {path}")
    elif path.exists():
        echo(f"  kept {path}: edited since Carter wrote it, or not recorded as Carter's")
    state.forget_file(path)


def _remove_git(base_dir: Path | None, state: GuardState, echo: Echo) -> None:
    """Take Carter's git config (include line, file, direct keys) away; a manual line is printed."""
    # the human added (or must add) the include line themselves: tell them to take it out
    ours = state.gitconfig is None and state.owned_unchanged(carter_gitconfig_path(base_dir))
    if ours and gitconfig.manual_include_state(base_dir) == "present":
        echo(
            "⚠ your global git config still has Carter's include line; remove it yourself:\n"
            f"    {gitconfig.unset_line(base_dir)}"
        )
    git = gitconfig.remove_all(base_dir, state)
    if git.include is not None and git.include.status == "manual":
        echo(f"⚠ {git.include.note}\n    {git.include.line}")
    elif git.include is not None and git.include.status == "absent":
        echo(f"  {git.include.note}")
    for name in git.files.removed:
        echo(f"  removed {name}")
    for name in git.files.kept:
        echo(f"  kept {name}: edited since Carter wrote it")


def _remove_repo_hooks(state: GuardState, echo: Echo) -> None:
    rem = repohooks.remove_owned(state)
    for name in rem.removed:
        echo(f"  removed repo hook {name}")
    for name in rem.kept:
        echo(f"  kept {name}: changed since Carter wrote it")


def _workspaces() -> list[str]:
    try:
        return list(load_identity().workspaces)
    except ConfigError:
        return []


def _repo_hooks_step(
    base_dir: Path | None, state: GuardState, echo: Echo, *, dry: bool, events: Sequence[str]
) -> None:
    """Install (or, in a dry run, only inspect) the owned hooks in the cwd repo and workspaces."""
    for repo in repohooks.repos_in_scope(Path.cwd(), _workspaces()):
        for event in events:
            found = repohooks.inspect(repo, state, base_dir, event)
            if found.state == "installable" and not dry:
                found = repohooks.install(repo, state, base_dir, event)
                echo(f"  repo hook installed: {found.hook}")
            elif found.state == "installable":
                echo(f"  would install a repo hook: {found.hook}")
            elif found.state == "guarded":
                echo(f"  repo hook present: {found.hook}")
            else:
                echo(f"⚠ {found.line()} ({event})")
                if found.snippet:
                    echo(f"    {found.snippet}")


def _accepted_rev(state: GuardState, group: str) -> int:
    """The revision the human accepted (1 when the record has none): decides the hook events."""
    return int(state.consents.get(group, {}).get("rev", 1))


def _git_step(
    base_dir: Path | None,
    state: GuardState,
    echo: Echo,
    *,
    dry_run: bool,
    mode: gitconfig.Mode | None,
) -> None:
    accepted = consent.accepted_groups(state)
    on_new_git = mode in ("include", "direct")
    want_hooks = "hooks" in accepted and on_new_git
    want_repo = "repo_hooks" in accepted and mode == "no-config-hooks"
    want_alias = "alias" in accepted and mode is not None
    hooks_rev = _accepted_rev(state, "hooks")
    repo_events = hooks.events_for_rev(_accepted_rev(state, "repo_hooks"))
    template: Path | None = None
    if want_repo:
        plan = repohooks.plan_template(gitconfig.global_config_path(), base_dir)
        if plan.status == "kept-user-value":
            echo(f"⚠ unguarded: templateDir. {plan.snippet}")
        else:
            template = plan.directory
    alias_set = False
    if want_alias:
        alias_plan = alias.plan_alias(gitconfig.global_config_path())
        alias_set = alias_plan.status != "kept-user-value"
        if not alias_set:
            echo(f"⚠ {alias_plan.snippet}")
    entries = gitconfig.carter_git_entries(
        [
            g
            for g, on in (("hooks", want_hooks), ("repo_hooks", want_repo), ("alias", want_alias))
            if on
        ],
        base_dir=base_dir,
        template_dir=template,
        hooks_rev=hooks_rev,
        alias=alias_set,
    )
    if want_hooks or want_repo:
        script = hooks.script_path(base_dir)
        echo(f"guard script: {script}" + (" (would be written)" if dry_run else ""))
        if not dry_run and hooks.install_script(base_dir, state) == "edited-kept":
            echo(
                f"⚠ kept your edited {script}; delete it and run `carter guard install` to restore"
            )
    if entries and not dry_run and template is not None:
        repohooks.install_template(base_dir, state, repo_events)
    if not entries:
        echo(GIT_NOT_NEEDED)
        withdrawn = not {"hooks", "repo_hooks", "alias"} & set(
            accepted
        )  # declined or never accepted
        if not dry_run and state.gitconfig is not None and withdrawn:
            _remove_git(base_dir, state, echo)  # a group was declined or withdrawn: reconcile
    else:
        echo(f"git config: {len(entries)} key(s), mode {mode}")
        target = gitconfig.global_config_path()
        if dry_run:
            if mode != "direct" and (why := gitconfig.manual_reason(target)) is not None:
                line = gitconfig.include_line(base_dir)
                echo(f"⚠ {why}; Carter would not write it. Add the line yourself:\n    {line}")
        else:
            _apply_entries(entries, base_dir, state, echo, mode=mode or "include")
    if want_repo:
        _repo_hooks_step(base_dir, state, echo, dry=dry_run, events=repo_events)
    if on_new_git and "hooks" in accepted and state.repo_hooks and not dry_run:
        echo(
            "git >= 2.54 is available: the config hook now covers every repo; removing the "
            "per-repo hooks Carter wrote earlier"
        )
        _remove_repo_hooks(state, echo)
        for old, version in repohooks.other_old_gits():
            echo(
                f"⚠ an older git is also installed ({old}, {version}): repos reached through it "
                "have no guard; `carter guard install --only repo_hooks` there"
            )


def _apply_entries(
    entries: list[gitconfig.Entry],
    base_dir: Path | None,
    state: GuardState,
    echo: Echo,
    *,
    mode: gitconfig.Mode,
) -> None:
    res = gitconfig.apply_keys(entries, mode=mode, base_dir=base_dir, state=state)
    if res.file == "edited-kept":
        echo(f"⚠ kept your edited {carter_gitconfig_path(base_dir)}; it is not rewritten")
    if res.include and res.include.status == "manual":
        echo(f"⚠ {res.include.note}\n    {res.include.line}")
    if res.direct:
        for line in res.direct.manual:
            echo(f"⚠ add by hand: {line}")
        for key in res.direct.conflicts:
            echo(f"⚠ kept your value for {key}")
    for key in res.needs_repo_hooks:
        echo(f"⚠ {key}: git < 2.54 needs the per-repo fallback (`repo_hooks`)")


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
        return _dry_run(base_dir, state, only, home, echo, today, *_availability(echo))

    def ask(group: ConsentGroup) -> bool:
        for line in group.explain:
            echo(line)
        question = f"{group.id}: {group.effect}\n  Install this group?"
        return confirm(question, default=True) if group.id == "repo_hooks" else confirm(question)

    mode, unavailable = _availability(echo)
    plan = consent.resolve_consents(
        state, only=only, assume_yes=assume_yes, interactive=interactive, ask=ask,
        unavailable=unavailable,
    )  # fmt: skip
    for note in plan.notices():
        echo(note)
    if plan.skipped:
        return 0
    if assume_yes:  # a confirmed revision is explained even when nobody is asked (--yes --only g2)
        for name in plan.asked:
            if name in plan.accepted and groups[name].rev > 1:
                for line in groups[name].explain:
                    echo(line)
    consent.record(state, plan, today=today)
    for name in plan.declined:
        if groups[name].optional:
            echo(
                f"Declined: {name} (optional; `carter guard install --only {name}` adds it later)."
            )
        else:
            echo(f"Declined: {name} (listed as a residual by `carter guard status`).")
    for name in plan.refused_offers:
        echo(
            f"Not confirmed: {name} revision 2 (denies stay; `carter guard install --only {name}`)"
        )
    if consent.plugin_wanted(state):
        plugin.plan(base_dir, state)  # preflight: E-FALSE-MISSING, bad paths... before any write
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
        _git_step(base_dir, state, echo, dry_run=False, mode=mode)
        if state != GuardState() or state_path.exists():
            save(state, state_path)
        if consent.plugin_wanted(state):
            plugin.install(base_dir, state, echo)
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
    if not consent.plugin_wanted(state):
        echo(INTERIM_NOTE)
    return 0


def _dry_run(
    base_dir: Path | None, state: GuardState, only: list[str] | None, home: str, echo: Echo,
    today: str, mode: gitconfig.Mode | None, unavailable: dict[str, str],
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
        if name in unavailable:
            echo(f"  {name:<18} not on this machine: {unavailable[name]}")
            continue
        if prior == "declined" and not (only and name in only):
            echo(f"  {name:<18} declined earlier (stays declined)")
            continue
        if group.optional and prior is None and not (only and name in only):
            echo(f"  {name:<18} optional, not part of --yes: `--only {name}` or a terminal yes")
            continue
        rec_rev = int(state.consents.get(name, {}).get("rev", 1))
        if prior == "accepted" and rec_rev < group.rev and not (only and name in only):
            echo(f"  {name:<18} accepted (revision {rec_rev}): {group.effect}")
            echo(
                f"  {'':<18} needs your confirmation for revision {group.rev}: plugin not installed"
            )
            continue
        status = prior or "would ask"
        echo(f"  {name:<18} {status}: {group.effect}")
        preview.consent(name, "accepted", today, group.rev)
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
    _git_step(base_dir, preview, echo, dry_run=True, mode=mode)
    if consent.plugin_wanted(preview):
        try:
            for item in plugin.plan(base_dir, preview):
                echo(f"  would write {item.path}")
            echo(f"  would create {plugin.run_dir(base_dir)}/gh-empty (0700)")
        except (plugin.PluginInstallError, IdentityError) as exc:
            echo(f"  ⚠ the plugin could not be planned: {exc}")
    verb = "updated" if state.consents else "created"
    echo(f"Guard state: {guard_state_path(base_dir)} (would be {verb})")
    if not consent.plugin_wanted(preview):
        echo(INTERIM_NOTE)
    return 0


# -- remove ---------------------------------------------------------------------------------


def _only_plugin(base_dir: Path | None, state: GuardState, echo: Echo, *, dry_run: bool) -> None:
    """``remove --only plugin``: plugin, ``isolation.json`` and ``run/`` go; the 1G denies, hooks
    and the PAT stay. ``g2`` goes back to revision 1 so a bare ``--yes`` never brings it back."""
    if dry_run:
        for item in (plugin.isolation_path(base_dir), plugin.plugin_dir(base_dir)):
            echo(f"  would remove {item}")
        echo("  g2 would go back to revision 1 (the 1G denies stay)")
        return
    plugin.remove(base_dir, state, echo)
    if state.consents.get("g2", {}).get("decision") == "accepted":
        state.consent("g2", "accepted", datetime.now(UTC).date().isoformat(), 1)
    echo("plugin removed; OpenCode unloads it within seconds (restart the server to be sure)")


def _only_broker(base_dir: Path | None, state: GuardState, echo: Echo, *, dry_run: bool) -> None:
    """``remove --only broker``: B goes off, the rest of ``g2`` stays.

    ``g2`` goes back to revision 2 (the plugin keeps its shell isolation), the plugin and
    ``isolation.json`` are re-rendered together with ``b_enabled: false``, the headless profile is
    removed, and the revision-3 offer is recorded as declined so nothing asks again."""
    if dry_run:
        echo("  g2 would go back to revision 2: B off, the rest of the plugin stays")
        echo(f"  would remove {plugin.headless_profile_path(base_dir)}")
        return
    day = datetime.now(UTC).date().isoformat()
    if state.consents.get("g2", {}).get("decision") == "accepted":
        state.consent("g2", "accepted", day, consent.PLUGIN_REV)
        state.record_offer("g2", consent.BROKER_REV, "declined", day)
    profile = plugin.headless_profile_path(base_dir)
    if state.owned_unchanged(profile):
        profile.unlink()
        echo(f"  removed {profile}")
    elif profile.exists():
        echo(f"  kept {profile}: changed since Carter wrote it")
    state.forget_file(profile)
    if consent.plugin_wanted(state):
        plugin.install(base_dir, state, echo)  # re-render isolation.json and the plugin together
    echo("B is off; OpenCode needs a restart to drop the tools")


def _known_extra_files(
    base_dir: Path | None, state: GuardState, echo: Echo, keep: Sequence[str] = ()
) -> None:
    """Delete recorded, unchanged files Carter installed; keep and report the rest.

    ``keep`` names the identity files (shim, mirror...): not the guards' to remove."""
    root = guard_state_path(base_dir).parent
    for rel in KNOWN_EXTRA_FILES:
        path = root / rel
        if path.exists() and not state.owned_unchanged(path):
            echo(f"  kept {path}: not recorded as Carter's, or changed since")
    for rec in list(state.files):
        path = Path(rec["path"])
        if rec["path"] in keep:
            continue
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
        names = [n for n in (only or []) if n not in (consent.PLUGIN, consent.BROKER)]
        for name in names:
            target.consents.pop(name, None)
        if names:
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
        if consent.PLUGIN in (only or []):
            _only_plugin(base_dir, target, echo, dry_run=dry_run)
        elif consent.BROKER in (only or []):
            _only_broker(base_dir, target, echo, dry_run=dry_run)
        elif "g2" in names and not dry_run:
            plugin.remove(base_dir, target, echo)  # the plugin belongs to g2
        hook_groups = [g for g in (only or []) if g in ("hooks", "repo_hooks", "alias")]
        if hook_groups and dry_run:
            echo(f"  (the git keys and files of {', '.join(hook_groups)} would be removed too)")
        elif hook_groups:
            # what stays accepted keeps its keys: only the withdrawn group's entries go
            mode, _ = _availability(echo)
            _git_step(base_dir, target, echo, dry_run=False, mode=mode)
            if "repo_hooks" in hook_groups:
                _remove_repo_hooks(target, echo)
            if not {"hooks", "repo_hooks"} & set(consent.accepted_groups(target)):
                _remove_script(base_dir, target, echo)
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
    plugin.remove(base_dir, state, echo)
    _remove_git(base_dir, state, echo)
    _remove_repo_hooks(state, echo)
    identity = mirror_io.identity_files(base_dir, state)
    _known_extra_files(base_dir, state, echo, identity)
    if (path.parent / "secrets" / "gh-read.token").exists():
        echo(PAT_KEPT)
    if identity:  # the shim's and the mirror's hash records stay: the guards are not theirs
        left = GuardState()
        left.files = [f for f in state.files if f["path"] in identity]
        save(left, path)
        echo("Kept the identity files and their records (`carter identity remove` takes them).")
        return 0
    path.unlink(missing_ok=True)
    echo("Removed guard state. (state/audit/ is kept.)")
    return 0
