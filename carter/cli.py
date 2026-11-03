"""Carter CLI — workspace scaffolding and management commands."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import click
from jinja2 import Environment

from carter.aplus.handoff import OWN_TERMINAL
from carter.config import (
    PROFILES,
    ConfigError,
    _validate_agent_suffix,
    _validate_docs_language,
    generate_default_config,
    identity_warnings,
    load_config,
)
from carter.harness import Expected, validate_agents
from carter.plans import parse_frontmatter, validate_checkpoint, validate_plans_dir
from carter.scaffold import (
    agent_filename,
    create_env,
    lint_policy,
    model_advisory,
    policy_notice,
    render_agents,
    render_instructions,
    write_rendered_files,
)
from carter.state import (
    KNOWLEDGE_FILES,
    StateError,
    add_to_gitignore,
    commit_state,
    init_workspace,
)


@click.group()
@click.version_option(package_name="carter-ai")
def main() -> None:
    """Carter AI — workspace scaffolding and management."""


@main.command()
@click.option("--mcp", is_flag=True, help="Install and configure MCP servers.")
@click.option(
    "--mcp-servers",
    "mcp_servers",
    default=None,
    help="Comma-separated subset of MCP servers to install (e.g. 'github,terraform'). "
    "Default: all. Only meaningful with --mcp.",
)
@click.option(
    "--bot-name",
    default=None,
    help="Deprecated and ignored. Attribution is configured with the LLM identity.",
)
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override install base directory (for testing).",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Also install the policy guards without asking. Without a terminal and without "
    "--yes they are skipped with a notice.",
)
@click.option("-q", "--quiet", is_flag=True, help="Errors only.")
@click.option("-v", "--verbose", is_flag=True, help="Detailed output.")
@click.option("--debug", is_flag=True, help="Debug output.")
def install(
    mcp: bool,
    mcp_servers: str | None,
    bot_name: str | None,
    base_dir: Path | None,
    assume_yes: bool,
    quiet: bool,
    verbose: bool,
    debug: bool,
) -> None:
    """Install Carter agents, skills, and MCP servers for OpenCode (>= 2.1).

    Then offers the policy guards (`carter guard install`). A guard problem exits 1 but
    never undoes the rest."""
    from carter.install.mcp import MCP_SERVERS
    from carter.install.orchestrator import run as run_install
    from carter.install.prereqs import PrerequisiteError

    if bot_name is not None:
        click.echo(
            "⚠  --bot-name is deprecated and ignored: attribution now comes from the LLM "
            "identity in ~/.carter/config.toml.",
            err=True,
        )

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


@main.command()
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override install base directory (for testing).",
)
@click.option("--keep-guards", is_flag=True, help="Leave policies, include line and guard state.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Remove the guards without asking.")
def uninstall(base_dir: Path | None, keep_guards: bool, assume_yes: bool) -> None:
    """Remove the Carter OpenCode install and, unless --keep-guards, the policy guards
    (only where unchanged since Carter wrote them; kept without a terminal or --yes)."""
    from carter.install.uninstall import uninstall as run_uninstall

    code = run_uninstall(base_dir, keep_guards=keep_guards, assume_yes=assume_yes)
    if code:
        raise SystemExit(code)


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--single", is_flag=True, help="Single-repo mode (default: umbrella)")
@click.option("--no-git-state", is_flag=True, help="Skip git init for state dirs")
@click.option("--name", default=None, help="Workspace name (default: directory name)")
@click.option(
    "--agent-suffix",
    default=None,
    help="Suffix for scaffolded agent names (default: local; '' for none).",
)
@click.option(
    "--profile",
    "profile",
    type=click.Choice(sorted(PROFILES)),
    default=None,
    help="Cost profile: 'quality' (all agents on Opus) or 'budget' (Sonnet where safe). "
    "Default: the shipped per-agent tiers.",
)
@click.option(
    "--docs-language",
    default=None,
    help="Language for Carter's internal docs (ADRs, RFCs, .carter/ plans and knowledge), "
    "e.g. 'es' or 'pt-BR' (default: en). Repository output is always English.",
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
    click.echo(f"Initialized .carter/ in {target}")

    # In single-repo mode, add .carter/ to .gitignore
    if single:
        add_to_gitignore(target)
        click.echo("Added .carter/ to .gitignore")

    # Render templates
    env = create_env()
    _render_and_write(target, config, env)

    click.echo(f"ℹ  {policy_notice(config)}")

    click.echo(f"Workspace '{workspace_name}' initialized ({mode} mode)")


def _stdin_is_tty() -> bool:
    import sys

    return sys.stdin.isatty()


def _pin_identity_policy(target: Path, config: dict, *, dry_run: bool, assume_yes: bool) -> None:
    """Copy ``identity.role``/``require_tier`` from carter.yaml into config.toml (D62).

    Shows the change and its source first, and writes only after a human confirms
    (``--yes`` or a TTY prompt). Raises ``click.ClickException`` when pinning is wanted
    but refused (cap below ``require_tier``, unmodelled keys, a broken or schema-1 file).
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
    if cfg.needs_migration:
        if role or tier:
            raise click.ClickException(
                "~/.carter/config.toml is schema 1; run `carter install` to migrate it "
                "before pinning identity policy."
            )
        return

    key = workspace_key(target)
    plan = plan_pin(cfg, key, role=role, require_tier=tier)
    if plan.refusal:
        raise click.ClickException(f"Identity policy not pinned: {plan.refusal}.")
    if not plan.changes:
        if role or tier:
            click.echo("Identity policy already pinned (no change).")
        return

    click.echo(f"Identity policy for {key} (source: .carter/carter.yaml)")
    for change in plan.changes:
        click.echo(f"  {change.field:<13} {change.old} -> {change.new}")
    if plan.max_tier:
        click.echo(
            f"  max_tier      {plan.max_tier} (hand-edited in config.toml; not changed here)"
        )
    if dry_run:
        click.echo("Would pin into ~/.carter/config.toml [workspaces] (dry run: nothing written).")
        return
    if not assume_yes:
        if not _stdin_is_tty():
            click.echo("Not pinned: run `carter update` in a terminal, or pass --yes.")
            return
        if not click.confirm("Pin this policy into ~/.carter/config.toml?"):
            click.echo("Not pinned.")
            return
    try:
        apply_pin(cfg, plan)
    except (WriterError, ConfigError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Pinned into ~/.carter/config.toml.")


def _refresh_policies(*, dry_run: bool, assume_yes: bool) -> None:
    """D52 (RFC-0007 C.6.2): turn ``allow_project_opencode_edit`` into policy statements.

    Only where policies were installed with consent; only from a human's shell. Everything
    is skipped, with a note, if ``config.toml`` cannot be read: ``update`` never fails here."""
    from datetime import datetime

    from carter.guard.optout import refresh_from_update
    from carter.identity import ConfigError, load_identity
    from carter.install.paths import backups_dir, guard_state_path
    from carter.terminal import is_agent_shell

    try:
        cfg = load_identity()
    except ConfigError:
        click.echo("ℹ  config.toml is invalid; D52 opt-outs not refreshed.")
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    refresh_from_update(
        None,
        guard_state_path(None),
        cfg,
        home=str(Path.home()),
        backup_root=backups_dir(None) / stamp,
        assume_yes=assume_yes,
        dry_run=dry_run,
        interactive=_stdin_is_tty(),
        agent=is_agent_shell(),
        confirm=click.confirm,
        echo=click.echo,
    )


# What a workspace AGENTS.md must contain to be current: (marker text, rendered line prefix).
_WORKSPACE_RULES = (("coauthor_trailer", "- **Commits**"), (OWN_TERMINAL, "- **Pushing**"))


def _note_stale_workspace_rules(target: Path, config: dict, env: Environment) -> None:
    """Workspace-level upgrade note: ``AGENTS.md`` is never rewritten, so say so when it lacks
    the tier-based commit rule or the human-only push rule. (The global note belongs to
    ``carter install``.)"""
    instructions = _instructions_path(target)
    if not instructions.exists():
        return
    have = instructions.read_text()
    lines = render_instructions(config, env)["AGENTS.md"].splitlines()
    missing = [
        next((line for line in lines if line.startswith(prefix)), "")
        for marker, prefix in _WORKSPACE_RULES
        if marker not in have
    ]
    if missing:
        rules = "\n   ".join(missing)
        click.echo(
            f"ℹ  {instructions.relative_to(target)} was not rewritten (it may hold your edits) and "
            f"its rules are out of date. Current rules:\n   {rules}"
        )


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, help="Preview changes without writing")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Pin identity policy without asking.")
def update(target_dir: str, dry_run: bool, assume_yes: bool) -> None:
    """Re-render templated files from carter.yaml and pin its identity policy.

    `identity.role` and `identity.require_tier` in carter.yaml take effect only here:
    update shows them, asks, and pins them in ~/.carter/config.toml.
    """
    target = Path(target_dir).resolve()
    config_path = target / ".carter" / "carter.yaml"

    try:
        config = load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e

    for warning in identity_warnings(config):
        click.echo(f"⚠  {warning}")
    _pin_identity_policy(target, config, dry_run=dry_run, assume_yes=assume_yes)
    _refresh_policies(dry_run=dry_run, assume_yes=assume_yes)

    env = create_env()

    if dry_run:
        agents = render_agents(config, env)
        click.echo("Would render:")
        agents_dir = _agents_dir(target)
        for name in sorted(agents):
            click.echo(f"  {(agents_dir / name).relative_to(target)}")
        instr = _instructions_path(target)
        note = " (skipped: exists)" if instr.exists() else ""
        click.echo(f"  {instr.relative_to(target)}{note}")
        return

    _render_and_write(target, config, env)
    click.echo(f"ℹ  {policy_notice(config)}")
    click.echo("Templates re-rendered from carter.yaml")
    _note_stale_workspace_rules(target, config, env)


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--no-harness",
    is_flag=True,
    help="Skip the `opencode debug agents` harness validation step.",
)
@click.option(
    "--host",
    is_flag=True,
    help="Check this machine instead (policies, guard files, git include); read-only.",
)
def check(target_dir: str, no_harness: bool, host: bool) -> None:
    """Validate workspace integrity and that OpenCode loads the Carter agents."""
    if host:
        from carter.hostcheck import exit_code, render, run_host_checks

        items = run_host_checks(cwd=Path(target_dir).resolve())
        click.echo("\n".join(render(items)))
        raise SystemExit(exit_code(items))
    target = Path(target_dir).resolve()
    config_path = target / ".carter" / "carter.yaml"
    errors: list[str] = []
    warnings: list[str] = []  # reported, never change the exit code

    # Check config exists
    if not config_path.exists():
        raise click.ClickException(
            f"Not a Carter workspace: {config_path} not found. Run 'carter init' first."
        )

    try:
        config = load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e

    warnings.extend(identity_warnings(config))

    # Check agent and instruction files exist in OpenCode's discovery paths,
    # collecting each role's parsed frontmatter for the policy lint as we go.
    installed: dict[str, dict] = {}
    agents_dir = _agents_dir(target)
    for agent_name in config["agents"]:
        agent_file = agents_dir / agent_filename(agent_name, config)
        if not agent_file.exists():
            errors.append(f"Missing agent file: {agent_file.relative_to(target)}")
            continue
        parsed = parse_frontmatter(agent_file.read_text())
        if parsed is None:
            errors.append(f"Unparseable frontmatter: {agent_file.relative_to(target)}")
        else:
            installed[agent_name] = parsed

    instructions_file = _instructions_path(target)
    if not instructions_file.exists():
        errors.append(f"Missing instructions: {instructions_file.relative_to(target)}")

    # Check knowledge files
    knowledge_dir = target / ".carter" / "knowledge"
    for filename in KNOWLEDGE_FILES:
        if not (knowledge_dir / filename).exists():
            errors.append(f"Missing knowledge file: .carter/knowledge/{filename}")

    # Validate plan frontmatter contract; thresholds from config
    plans_root = target / ".carter" / "state" / "plans"
    plans_result = validate_plans_dir(plans_root, config.get("plans"))
    errors.extend(plans_result.errors)
    warnings.extend(plans_result.warnings)

    # Validate the session checkpoint cursor (absent is fine); cross-check that
    # its active_plan resolves to a real plan under active/.
    checkpoint = target / ".carter" / "state" / "sessions" / "checkpoint.md"
    errors.extend(validate_checkpoint(checkpoint, plans_root))

    # Lint emitted `permissions:`/`model` against what carter.yaml generates.
    errors.extend(lint_policy(config, installed))

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
            click.echo(f"⚠  {harness_result.warning}", err=True)
        errors.extend(harness_result.errors)
        if harness_result.status == "ok":
            click.echo(f"OpenCode loaded all {len(expected)} Carter agents")

    if warnings:
        click.echo("Workspace warnings:", err=True)
        for warning in warnings:
            click.echo(f"  ⚠ {warning}", err=True)

    if errors:
        click.echo("Workspace issues found:", err=True)
        for error in errors:
            click.echo(f"  ✗ {error}", err=True)
        raise SystemExit(1)

    # Required unverifiable-model advisory — always printed.
    click.echo(f"ℹ  {model_advisory(config)}")

    click.echo("Workspace OK")


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--message", "-m", default=None, help="Commit message for the state snapshot.")
def save(target_dir: str, message: str | None) -> None:
    """Commit the .carter/ workspace state (recovery checkpoint).

    Snapshots plans, sessions, and knowledge into the nested .carter/.git so a
    deleted plan or session is recoverable. No-op if there is nothing to commit
    or the workspace was initialized with --no-git-state.
    """
    from datetime import datetime

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
        click.echo("Saved .carter/ state")
    else:
        click.echo("Nothing to save (no changes or git state disabled)")


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
    path.write_text(content)
    return True


def _render_and_write(target: Path, config: dict, env: Environment) -> None:
    """Render templates and write them to OpenCode's discovery paths.

    Carter-owned agent files (``carter-*``) are always (re)written so that
    ``carter update`` refreshes them. ``AGENTS.md`` is written only when absent
    (skip-if-exists), so user edits are preserved.
    """
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
    """Carter-ops audit ledger and config helper (used by the carter-ops skill).

    All arguments are passed through to the carter-ops CLI, e.g.:

        carter ops audit --operation git-flow --result success
        carter ops policy-override --category remote-write --action "vault read x" --tier native-ask
        carter ops config --emit
    """
    from carter.ops.carter_ops import main as ops_main

    raise SystemExit(ops_main(list(args)))


def _register_guard() -> None:
    from carter.guard.cli import guard

    main.add_command(guard)


def _register_github_token() -> None:
    from carter.ghtoken_cli import github_token

    main.add_command(github_token)


def _register_aplus() -> None:
    from carter.aplus_cli import pr, push

    main.add_command(push)
    main.add_command(pr)


_register_guard()
_register_github_token()
_register_aplus()


if __name__ == "__main__":
    main()
