"""Carter CLI — workspace scaffolding and management commands."""

from __future__ import annotations

import os
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import click

from carter import ui
from carter.cliguard import LazyGroup, verbose_option

if TYPE_CHECKING:
    from jinja2 import Environment

# Imports stay inside the command bodies: `carter --help` and Tab completion must not load
# jinja2, yaml or the network stack (tests/test_startup.py holds the line).

# The subcommands that live in their own modules: name -> ("module:attr", one-line summary).
# The summary is what `carter --help` lists without importing the module: the first line of
# the command's docstring, kept equal by tests/test_help.py.
_LAZY = {
    "ci": ("carter.ci_cli:ci", "Review-only CI workflow: no commits, read-only."),
    "commit": (
        "carter.commit_cli:commit_cmd",
        "Commit as the LLM identity (git commit arguments).",
    ),
    "gate": ("carter.gate_cli:gate", "Inspect the command gate."),
    "github-token": (
        "carter.ghtoken_cli:github_token",
        "Store and check the read-only GitHub token.",
    ),
    "guard": ("carter.guard.cli:guard", "Install, inspect and remove Carter's guards."),
    "identity": (
        "carter.identity_cli:identity",
        "The LLM identity: set it up, check it, unlock its key.",
    ),
    "push": ("carter.aplus_cli:push", "Push the current branch to origin (never forced)."),
}
_PROFILE_NAMES = ("budget", "quality")  # config.PROFILES; a test keeps them equal


@click.group(cls=LazyGroup, lazy=_LAZY)
@click.version_option(package_name="carter-ai")
@click.option(
    "--no-color",
    is_flag=True,
    expose_value=False,
    hidden=True,
    callback=lambda _c, _p, v: ui.configure(color=False) if v else None,
)
@verbose_option
def main() -> None:
    """Carter AI: agents, guards and the LLM identity for OpenCode."""


@main.command()
@click.option("--mcp", is_flag=True, help="Also set up MCP servers.")
@click.option(
    "--mcp-servers",
    "mcp_servers",
    default=None,
    help="MCP servers to set up, comma-separated (default: all).",
)
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    hidden=True,
    help="Install elsewhere (testing).",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Install the guards without asking.")
@click.option("-q", "--quiet", is_flag=True, help="Errors only.")
@click.option("-v", "--verbose", is_flag=True, help="More detail.")
@click.option("--debug", is_flag=True, help="Debug output.")
def install(
    mcp: bool,
    mcp_servers: str | None,
    base_dir: Path | None,
    assume_yes: bool,
    quiet: bool,
    verbose: bool,
    debug: bool,
) -> None:
    """Install the Carter agents, skills and guards for OpenCode."""
    from carter.install.mcp import MCP_SERVERS
    from carter.install.orchestrator import run as run_install
    from carter.install.prereqs import PrerequisiteError

    if verbose:
        ui.configure(verbose=True)  # the guard step prints its details too
    if quiet:
        verbosity = 0
    elif debug:
        verbosity = 3
    elif verbose:
        verbosity = 2
    else:
        verbosity = 1

    # Parse + validate the opt-in subset here so a bad name fails fast as a CLI error.
    servers: list[str] | None = None
    if mcp_servers is not None:
        servers = [s.strip() for s in mcp_servers.split(",") if s.strip()]
        unknown = [s for s in servers if s not in MCP_SERVERS]
        if unknown:
            raise click.BadParameter(
                f"Unknown MCP server(s): {', '.join(unknown)}. "
                f"Choose from: {', '.join(MCP_SERVERS)}.",
                param_hint="--mcp-servers",
            )

    try:
        guard_code = run_install(
            mcp=mcp,
            base_dir=base_dir,
            verbosity=verbosity,
            mcp_servers=servers,
            guards=True,
            assume_yes=assume_yes,
        )
    except PrerequisiteError as exc:
        raise click.ClickException(f"{exc} Nothing was installed.") from exc
    if guard_code:
        raise SystemExit(guard_code)
    if verbosity:
        ui.gap()
        ui.next("restart the OpenCode server from a clean terminal to load the agents and plugin")


@main.command()
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    hidden=True,
    help="Uninstall from elsewhere (testing).",
)
@click.option("--keep-guards", is_flag=True, help="Leave the guards in place.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, hidden=True)
@verbose_option
def uninstall(base_dir: Path | None, keep_guards: bool, assume_yes: bool) -> None:
    """Remove the Carter agents and skills, and the guards."""
    from carter.install.uninstall import uninstall as run_uninstall

    report = run_uninstall(base_dir, keep_guards=keep_guards, assume_yes=assume_yes)
    if report.code:
        raise SystemExit(report.code)


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--single", is_flag=True, help="One repo (default: umbrella).")
@click.option("--no-git-state", is_flag=True, help="Skip git init for the state dir.")
@click.option("--name", default=None, help="Workspace name (default: the directory).")
@click.option(
    "--agent-suffix",
    default=None,
    help="Agent name suffix (default: local).",
)
@click.option(
    "--profile",
    "profile",
    type=click.Choice(_PROFILE_NAMES),
    default=None,
    help="quality (all Opus) or budget (Sonnet where safe).",
)
@click.option(
    "--docs-language",
    default=None,
    help="Language of internal docs, e.g. es (default: en).",
)
def init(
    target_dir: str,
    single: bool,
    no_git_state: bool,
    name: str | None,
    agent_suffix: str | None,
    profile: str | None,
    docs_language: str | None,
) -> None:
    """Initialize a Carter workspace."""
    from carter.config import (
        ConfigError,
        _validate_agent_suffix,
        _validate_docs_language,
        generate_default_config,
    )
    from carter.home import remember_workspace
    from carter.scaffold import create_env, policy_notice
    from carter.state import add_to_gitignore, init_workspace

    target = Path(target_dir).resolve()
    workspace_name = name or target.name
    mode = "single" if single else "umbrella"

    # Generate default config, applying CLI overrides before it is persisted so
    # carter.yaml matches what was scaffolded.
    config = generate_default_config(workspace_name=workspace_name, mode=mode)
    if agent_suffix is not None:
        try:
            _validate_agent_suffix(agent_suffix)
        except ConfigError as e:
            raise click.BadParameter(str(e), param_hint="--agent-suffix") from e
        config["agent_suffix"] = agent_suffix
    # `profile:` is seeded only when chosen — an absent key keeps carter.yaml minimal and
    # resolves to the shipped default tiers (click.Choice already rejects a bad value).
    if profile is not None:
        config["profile"] = profile
    if docs_language is not None:
        try:
            _validate_docs_language(docs_language)
        except ConfigError as e:
            raise click.BadParameter(str(e), param_hint="--docs-language") from e
        config["docs_language"] = docs_language

    # Create .carter/ structure
    init_workspace(
        target_dir=target,
        config=config,
        git_state=not no_git_state,
    )
    remember_workspace(target)
    ui.detail(f"initialized .carter/ in {target}")

    # In single-repo mode, add .carter/ to .gitignore
    if single:
        add_to_gitignore(target)
        ui.detail("added .carter/ to .gitignore")

    # Render templates
    env = create_env()
    _render_and_write(target, config, env)

    ui.detail(policy_notice(config))

    ui.ok(f"workspace '{workspace_name}' initialized", f"{mode} mode")


def _pin_identity_policy(target: Path, config: dict, *, dry_run: bool) -> None:
    """Copy ``identity.role``/``require_tier`` from carter.yaml into config.toml.

    Asks nothing; an agent shell never pins. Raises ``click.ClickException`` when
    pinning is wanted but refused (cap below ``require_tier``, unmodelled keys, a broken file).
    """
    from carter.identity import ConfigError, load_identity
    from carter.identity.pin import apply_pin, plan_pin
    from carter.identity.workspace import workspace_key
    from carter.identity.writer import WriterError

    identity = config.get("identity") or {}
    role, tier = identity.get("role") or "", identity.get("require_tier") or ""
    try:
        cfg = load_identity()
    except ConfigError as exc:
        if role or tier:
            raise click.ClickException(
                f"config.toml is invalid ({exc.code}: {exc.detail}); identity policy not pinned."
            ) from exc
        return

    key = workspace_key(target)
    plan = plan_pin(cfg, key, role=role, require_tier=tier)
    if plan.refusal:
        raise click.ClickException(f"Identity policy not pinned: {plan.refusal}.")
    if not plan.changes:
        if role or tier:
            ui.detail("identity policy already pinned")
        return

    ui.detail(f"identity policy for {key} (source: .carter/carter.yaml)")
    for change in plan.changes:
        ui.detail(f"{change.field:<13} {change.old} -> {change.new}")
    if plan.max_tier:
        ui.detail(f"max_tier      {plan.max_tier} (hand-edited in config.toml; not changed here)")
    what = ", ".join(f"{c.field} {c.new}" for c in plan.changes)
    if dry_run:
        ui.info(f"would pin {what} (dry run: nothing written)")
        return
    from carter.terminal import is_agent_shell

    if is_agent_shell():
        ui.warn("identity policy not pinned: agent shells never pin it", "run `carter update`")
        return
    try:
        apply_pin(cfg, plan)
    except (WriterError, ConfigError) as exc:
        raise click.ClickException(str(exc)) from exc
    unpinned = all(c.new == "(unset)" for c in plan.changes)
    ui.ok("identity policy unpinned" if unpinned else "identity policy pinned", what)


def _sync_mirror(*, dry_run: bool) -> None:
    """regenerate ``carter.tier`` and the cap fragments in ``~/.carter/gitconfig``.

    Asks nothing; an agent shell never writes it. Never fails ``update`` for a config
    problem; a cap below ``require_tier`` is refused."""
    from carter.guard import update_mirror
    from carter.identity import ConfigError, load_identity
    from carter.terminal import is_agent_shell

    try:
        cfg = load_identity()
    except ConfigError:
        ui.warn("config.toml is invalid; the hook tier was not refreshed")
        return
    plan = update_mirror.plan(None, cfg)
    if plan.refusal:
        raise click.ClickException(f"Hook tier not written: {plan.refusal}.")
    if not plan.changes:
        return
    for line in plan.lines():
        ui.detail(line.strip())
    if dry_run:
        ui.info("would write the hook tier (dry run: nothing written)")
        return
    if is_agent_shell():
        ui.warn("hook tier not written: agent shells never change it", "run `carter update`")
        return
    try:
        update_mirror.apply(None, cfg)
    except Exception as exc:  # GitError, MirrorError, IdentityError (E-STATE-INVALID)
        from carter.guard.engine import format_error

        text = format_error(exc) or str(exc)
        raise click.ClickException(f"Hook tier not written: {text}") from exc
    ui.ok("hook tier written")
    hint = update_mirror.include_hint(None)
    if hint:
        ui.warn("add Carter's include line to your git config yourself", hint)


def _report_unknown_keys(target: Path) -> None:
    """at the end of ``update``: each leftover key once, workspace files then host files."""
    from carter import unknownkeys

    hits = [*unknownkeys.workspace(target), *unknownkeys.host()]
    unknownkeys.report(unknownkeys.once_per_key(hits))


def _refresh_agents(*, dry_run: bool) -> None:
    """and: the global Carter agent files carry G2's rules, including the opt-outs read
    from ``config.toml``. Re-render them from a human's shell when they differ; ``update`` never
    fails here."""
    from carter.guard.agent_rules import current_rules
    from carter.install import components
    from carter.terminal import is_agent_shell

    if not current_rules():
        return  # no guards installed with consent: update never creates any
    if dry_run:
        ui.detail("the global Carter agent files would be refreshed (dry run)")
        return
    if is_agent_shell():
        ui.warn("global Carter agents not refreshed: agent shells never change them")
        return
    try:
        stats = components.rerender_agents(None)
    except OSError as exc:
        ui.warn(f"global Carter agents not refreshed ({type(exc).__name__})")
        return
    if stats and stats["updated"] + stats["created"]:
        ui.ok("global Carter agents refreshed", f"{stats['updated'] + stats['created']} file(s)")


def _note_stale_workspace_rules(target: Path, config: dict, env: Environment) -> None:
    """Workspace-level upgrade note: ``AGENTS.md`` is never rewritten, so say so when it lacks
    the tier-based commit rule or the human-only push rule. (The global note belongs to
    ``carter install``.)"""
    from carter.aplus.push import OWN_TERMINAL
    from carter.scaffold import render_instructions

    instructions = _instructions_path(target)
    if not instructions.exists():
        return
    have = instructions.read_text(encoding="utf-8")
    lines = render_instructions(config, env)["AGENTS.md"].splitlines()
    # What a workspace AGENTS.md must contain to be current: (marker text, rendered line prefix).
    required = (("coauthor_trailer", "- **Commits**"), (OWN_TERMINAL, "- **Pushing**"))
    missing = [
        next((line for line in lines if line.startswith(prefix)), "")
        for marker, prefix in required
        if marker not in have
    ]
    if missing:
        rules = "\n   ".join(missing)
        ui.warn(
            f"{instructions.relative_to(target)} has rules that are out of date "
            "(not rewritten: it may hold your edits)",
            rules,
        )


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, help="Show what would change; write nothing.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, hidden=True)
@verbose_option
def update(target_dir: str, dry_run: bool, assume_yes: bool) -> None:
    """Re-render the agents and apply carter.yaml."""
    from carter.config import ConfigError, load_config
    from carter.home import remember_workspace
    from carter.scaffold import create_env, policy_notice, render_agents

    del assume_yes  # accepted and ignored: update asks nothing
    target = Path(target_dir).resolve()
    config_path = target / ".carter" / "carter.yaml"

    try:
        config = load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e

    _pin_identity_policy(target, config, dry_run=dry_run)
    _sync_mirror(dry_run=dry_run)
    _refresh_agents(dry_run=dry_run)

    env = create_env()

    if dry_run:
        agents = render_agents(config, env)
        agents_dir = _agents_dir(target)
        for name in sorted(agents):
            ui.detail(str((agents_dir / name).relative_to(target)))
        instr = _instructions_path(target)
        note = " (skipped: exists)" if instr.exists() else ""
        ui.info(f"would render {len(agents)} agents and {instr.relative_to(target)}{note}")
        _report_unknown_keys(target)
        return

    # A workspace made before the record existed is listed from its first update.
    remember_workspace(target)
    _render_and_write(target, config, env)
    ui.detail(policy_notice(config))
    ui.ok("updated", f"{len(render_agents(config, env))} agents from carter.yaml")
    _note_stale_workspace_rules(target, config, env)
    _report_unknown_keys(target)


_UPDATE = "run `carter update`"
_EDIT = "fix the file named above, then run `carter check` again"


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--no-harness",
    is_flag=True,
    help="Skip the OpenCode agent check.",
)
@click.option(
    "--host",
    is_flag=True,
    help="Check this machine instead (read-only).",
)
@click.option(
    "--probe",
    is_flag=True,
    help="Probe an agent shell's isolation (the agent runs it).",
)
@verbose_option
def check(target_dir: str, no_harness: bool, host: bool, probe: bool) -> None:
    """Check the workspace, or this machine with --host."""
    if probe:
        if host:
            raise click.UsageError("--probe and --host cannot be used together.")
        from carter import terminal
        from carter.guard import probe as probes
        from carter.identity.errors import E_PROBE_SCOPE, IdentityError

        if not terminal.is_agent_shell():
            err = IdentityError(E_PROBE_SCOPE)
            raise click.ClickException(f"{err.code}: {err}")
        results = probes.run_probes(os.environ)
        click.echo("\n".join(r.line() for r in results))
        raise SystemExit(probes.exit_code(results))
    if host:
        from carter.hostcheck import live_readers, run_host_checks

        click.echo("checking GitHub...", err=True)  # the network calls below take a few seconds
        items = run_host_checks(cwd=Path(target_dir).resolve(), **live_readers())
        raise SystemExit(ui.items(items, "host"))
    from carter import unknownkeys
    from carter.config import ConfigError, load_config
    from carter.harness import Expected, validate_agents
    from carter.plans import parse_frontmatter, validate_checkpoint, validate_plans_dir
    from carter.scaffold import agent_filename, lint_policy, model_advisory, model_pins
    from carter.state import KNOWLEDGE_FILES

    target = Path(target_dir).resolve()
    config_path = target / ".carter" / "carter.yaml"
    errors: list[tuple[str, str]] = []  # (problem, the command that fixes it)
    warnings: list[str] = []  # reported, never change the exit code
    loaded = False

    # Check config exists
    if not config_path.exists():
        raise click.ClickException(
            f"Not a Carter workspace: {config_path} not found. Run 'carter init' first."
        )

    try:
        config = load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e

    # Check agent and instruction files exist in OpenCode's discovery paths,
    # collecting each role's parsed frontmatter for the policy lint as we go.
    installed: dict[str, dict] = {}
    agents_dir = _agents_dir(target)
    for agent_name in config["agents"]:
        agent_file = agents_dir / agent_filename(agent_name, config)
        if not agent_file.exists():
            errors.append((f"Missing agent file: {agent_file.relative_to(target)}", _UPDATE))
            continue
        parsed = parse_frontmatter(agent_file.read_text(encoding="utf-8"))
        if parsed is None:
            errors.append((f"Unparseable frontmatter: {agent_file.relative_to(target)}", _UPDATE))
        else:
            installed[agent_name] = parsed

    instructions_file = _instructions_path(target)
    if not instructions_file.exists():
        errors.append((f"Missing instructions: {instructions_file.relative_to(target)}", _UPDATE))

    # Check knowledge files
    knowledge_dir = target / ".carter" / "knowledge"
    for filename in KNOWLEDGE_FILES:
        if not (knowledge_dir / filename).exists():
            errors.append(
                (f"Missing knowledge file: .carter/knowledge/{filename}", "run `carter init`")
            )

    # Validate plan frontmatter contract; thresholds from config
    plans_root = target / ".carter" / "state" / "plans"
    plans_result = validate_plans_dir(plans_root, config.get("plans"))
    errors.extend((e, _EDIT) for e in plans_result.errors)

    # Validate the session checkpoint cursor (absent is fine); cross-check that
    # its active_plan resolves to a real plan under active/.
    checkpoint = target / ".carter" / "state" / "sessions" / "checkpoint.md"
    errors.extend((e, _EDIT) for e in validate_checkpoint(checkpoint, plans_root))

    # Lint emitted `permissions:`/`model` against what carter.yaml generates.
    errors.extend((e, _UPDATE) for e in lint_policy(config, installed))

    # Harness validation: OpenCode must actually load every agent.
    if not no_harness:
        expected: dict[str, Expected] = {}
        mtimes: list[float] = []
        for role in config["agents"]:
            agent_file = agents_dir / agent_filename(role, config)
            if not agent_file.exists():
                continue  # already reported as a missing file
            mtimes.append(agent_file.stat().st_mtime)
            meta = installed.get(role, {})
            perms, desc, model = meta.get("permissions"), meta.get("description"), meta.get("model")
            expected[agent_file.stem] = Expected(
                rules=perms if isinstance(perms, list) else None,
                description=desc if isinstance(desc, str) else None,
                model=model if isinstance(model, str) else None,
            )
        harness_result = validate_agents(
            target, expected, newest_change=max(mtimes) if mtimes else None
        )
        if harness_result.warning:
            ui.warn(harness_result.warning)
        # Missing-agent and stale-config lines name their own `carter` command; only an
        # OpenCode that did not answer carries a fix of its own (re-rendering would not help).
        errors.extend((e, harness_result.fix) for e in harness_result.errors)
        loaded = harness_result.status == "ok"

    for warning in warnings:
        ui.warn(warning)
    unknownkeys.report(unknownkeys.workspace(target))

    if errors:
        for error, fix in errors:
            ui.fail(error, fix)
        ui.fail(f"workspace: {len(errors)} problem{'s' if len(errors) != 1 else ''}")
        raise SystemExit(1)

    # The model pins cannot be verified, so every passing check says so (one line; -v adds roles).
    ui.info(model_advisory(config))
    for role, model in model_pins(config):
        ui.detail(f"{role}: {model}")

    ui.ok(
        "Workspace OK",
        f"{len(config['agents'])} agents"
        + (" · loaded by OpenCode" if loaded else "")
        + (f" · {len(warnings)} warnings" if warnings else ""),
    )


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--message", "-m", default=None, help="Commit message.")
def save(target_dir: str, message: str | None) -> None:
    """Commit the .carter/ workspace state (a recovery checkpoint)."""
    from datetime import datetime

    from carter.state import StateError, commit_state

    target = Path(target_dir).resolve()
    carter_dir = target / ".carter"
    if not carter_dir.exists():
        raise click.ClickException(
            f"Not a Carter workspace: {carter_dir} not found. Run 'carter init' first."
        )

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = message or f"chore: checkpoint state ({stamp})"
    try:
        saved = commit_state(carter_dir, msg)
    except StateError as e:
        raise click.ClickException(str(e)) from e
    if saved:
        ui.ok("saved .carter/ state")
    else:
        ui.info("nothing to save (no changes, or git state is off)")


# OpenCode discovery paths (relative to the workspace root): agents in
# .opencode/agents/*.md, instructions in AGENTS.md at the project root.
_AGENT_DIR = Path(".opencode") / "agents"
_INSTRUCTION_PATH = Path("AGENTS.md")


def _agents_dir(target_root: Path) -> Path:
    return target_root / _AGENT_DIR


def _instructions_path(target_root: Path) -> Path:
    return target_root / _INSTRUCTION_PATH


def _write_if_absent(path: Path, content: str) -> bool:
    """Write ``content`` to ``path`` only if it does not already exist.

    Returns True if written, False if skipped. Used for instruction files
    (``AGENTS.md``) which may carry user content
    and must never be clobbered.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _render_and_write(target: Path, config: dict, env: Environment) -> None:
    """Render templates and write them to OpenCode's discovery paths.

    Carter-owned agent files (``carter-*``) are always (re)written so that
    ``carter update`` refreshes them. ``AGENTS.md`` is written only when absent
    (skip-if-exists), so user edits are preserved.
    """
    from carter.scaffold import render_agents, render_instructions, write_rendered_files

    agents = render_agents(config, env)
    instructions_content = render_instructions(config, env)["AGENTS.md"]
    write_rendered_files(agents, _agents_dir(target))
    _write_if_absent(_instructions_path(target), instructions_content)


@main.command(
    "ops",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        "help_option_names": [],
    },
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def ops(args: tuple[str, ...]) -> None:
    """Audit and config helper used by the carter-ops skill.

    \b
    carter ops audit --operation git-flow --result success
    carter ops config --emit [--field NAME]
    carter ops policy-override --category remote-write --action "vault read x" --tier native-ask
    """
    from carter.ops.carter_ops import main as ops_main

    raise SystemExit(ops_main(list(args)))


if __name__ == "__main__":
    main()
