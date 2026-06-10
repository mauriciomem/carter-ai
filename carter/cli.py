"""Carter CLI — workspace scaffolding and management commands."""
from __future__ import annotations

from pathlib import Path

import click

from carter.config import ConfigError, _validate_agent_suffix, generate_default_config, load_config
from carter.plans import validate_checkpoint, validate_plans_dir
from carter.scaffold import (    agent_filename,
    config_warnings,
    create_env,
    render_agents,
    render_instructions,
    write_rendered_files,
)
from carter.state import StateError, add_to_gitignore, commit_state, init_workspace


@click.group()
@click.version_option(package_name="carter-ai")
def main():
    """Carter AI — workspace scaffolding and management."""


@main.command()
@click.option(
    "--target",
    type=click.Choice(["copilot", "opencode", "all"]),
    default="all",
    help="Install target (default: all).",
)
@click.option("--mcp", is_flag=True, help="Install and configure MCP servers.")
@click.option(
    "--bot-name",
    default="carter-bot",
    help="Git commit author name for carter-ops attribution.",
)
@click.option("--uninstall", "uninstall_flag", is_flag=True, help="Remove Carter installation.")
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override install base directory (for testing).",
)
@click.option("-q", "--quiet", is_flag=True, help="Errors only.")
@click.option("-v", "--verbose", is_flag=True, help="Detailed output.")
@click.option("--debug", is_flag=True, help="Debug output.")
def install(
    target: str,
    mcp: bool,
    bot_name: str,
    uninstall_flag: bool,
    base_dir: Path | None,
    quiet: bool,
    verbose: bool,
    debug: bool,
):
    """Install Carter agents, skills, and MCP servers system-wide (~/.copilot/)."""
    from carter.installer import run as run_install

    if quiet:
        verbosity = 0
    elif debug:
        verbosity = 3
    elif verbose:
        verbosity = 2
    else:
        verbosity = 1

    run_install(
        target=target,
        mcp=mcp,
        bot_name=bot_name,
        uninstall_flag=uninstall_flag,
        base_dir=base_dir,
        verbosity=verbosity,
    )


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--single", is_flag=True, help="Single-repo mode (default: umbrella)")
@click.option("--no-git-state", is_flag=True, help="Skip git init for state dirs")
@click.option("--name", default=None, help="Workspace name (default: directory name)")
@click.option(
    "--target",
    "target_tool",
    type=click.Choice(["copilot", "opencode", "all"]),
    default=None,
    help="Where to write agents/instructions (default: copilot).",
)
@click.option(
    "--agent-suffix",
    default=None,
    help="Suffix for scaffolded agent names (default: local; '' for none).",
)
def init(
    target_dir: str,
    single: bool,
    no_git_state: bool,
    name: str | None,
    target_tool: str | None,
    agent_suffix: str | None,
):
    """Initialize a Carter workspace."""
    target = Path(target_dir).resolve()
    workspace_name = name or target.name
    mode = "single" if single else "umbrella"

    # Generate default config, applying CLI overrides before it is persisted so
    # carter.yaml matches what was scaffolded.
    config = generate_default_config(workspace_name=workspace_name, mode=mode)
    config["state"]["git_tracked"] = not no_git_state
    if target_tool is not None:
        config["target"] = target_tool
    if agent_suffix is not None:
        try:
            _validate_agent_suffix(agent_suffix)
        except ConfigError as e:
            raise click.BadParameter(str(e), param_hint="--agent-suffix") from e
        config["agent_suffix"] = agent_suffix

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

    for warning in config_warnings(config):
        click.echo(f"⚠  {warning}", err=True)

    click.echo(f"Workspace '{workspace_name}' initialized ({mode} mode)")


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, help="Preview changes without writing")
def update(target_dir: str, dry_run: bool):
    """Re-render templated files from carter.yaml."""
    target = Path(target_dir).resolve()
    config_path = target / ".carter" / "carter.yaml"

    try:
        config = load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e

    env = create_env()

    if dry_run:
        agents = render_agents(config, env)
        tools = _resolve_targets(config.get("target", "copilot"))
        click.echo("Would render:")
        for tool in tools:
            agents_dir = _agents_dir(target, tool)
            for name in sorted(agents):
                click.echo(f"  {(agents_dir / name).relative_to(target)}")
            instr = _instructions_path(target, tool)
            note = " (skipped: exists)" if instr.exists() else ""
            click.echo(f"  {instr.relative_to(target)}{note}")
        return

    _render_and_write(target, config, env)
    for warning in config_warnings(config):
        click.echo(f"⚠  {warning}", err=True)
    click.echo("Templates re-rendered from carter.yaml")


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
def check(target_dir: str):
    """Validate workspace integrity."""
    target = Path(target_dir).resolve()
    config_path = target / ".carter" / "carter.yaml"
    errors: list[str] = []

    # Check config exists
    if not config_path.exists():
        raise click.ClickException(
            f"Not a Carter workspace: {config_path} not found. Run 'carter init' first."
        )

    try:
        config = load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e

    # Check agent and instruction files exist in each target's discovery path
    for tool in _resolve_targets(config.get("target", "copilot")):
        agents_dir = _agents_dir(target, tool)
        for agent_name in config["agents"]:
            agent_file = agents_dir / agent_filename(agent_name, config)
            if not agent_file.exists():
                errors.append(f"Missing agent file: {agent_file.relative_to(target)}")

        instructions_file = _instructions_path(target, tool)
        if not instructions_file.exists():
            errors.append(f"Missing instructions: {instructions_file.relative_to(target)}")

    # Check knowledge files
    knowledge_dir = target / ".carter" / "knowledge"
    for filename in ["lessons-learned.md", "gotchas.md", "tools.md", "decisions.md", "patterns.md"]:
        if not (knowledge_dir / filename).exists():
            errors.append(f"Missing knowledge file: .carter/knowledge/{filename}")

    # Validate plan frontmatter contract (ADR-0003); thresholds from config
    plans_root = target / ".carter" / "state" / "plans"
    errors.extend(validate_plans_dir(plans_root, config.get("plans")))

    # Validate the session checkpoint cursor (absent is fine); cross-check that
    # its active_plan resolves to a real plan under active/.
    checkpoint = target / ".carter" / "state" / "sessions" / "checkpoint.md"
    errors.extend(validate_checkpoint(checkpoint, plans_root))

    if errors:
        click.echo("Workspace issues found:", err=True)
        for error in errors:
            click.echo(f"  ✗ {error}", err=True)
        raise SystemExit(1)

    for warning in config_warnings(config):
        click.echo(f"⚠  {warning}", err=True)

    click.echo("Workspace OK")


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--message", "-m", default=None, help="Commit message for the state snapshot.")
def save(target_dir: str, message: str | None):
    """Commit the .carter/ workspace state (recovery checkpoint).

    Snapshots plans, sessions, and knowledge into the nested .carter/.git so a
    deleted plan or session is recoverable. No-op if there is nothing to commit
    or the workspace was initialized with --no-git-state.
    """
    from datetime import datetime, timezone

    target = Path(target_dir).resolve()
    carter_dir = target / ".carter"
    if not carter_dir.exists():
        raise click.ClickException(
            f"Not a Carter workspace: {carter_dir} not found. Run 'carter init' first."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = message or f"chore: checkpoint state ({stamp})"
    try:
        saved = commit_state(carter_dir, msg)
    except StateError as e:
        raise click.ClickException(str(e)) from e
    if saved:
        click.echo("Saved .carter/ state")
    else:
        click.echo("Nothing to save (no changes or git state disabled)")



def _resolve_targets(target: str) -> list[str]:
    """Resolve a config ``target`` value to concrete tool targets.

    Mirrors the installer: ``all`` expands to both, anything else is itself.
    """
    return ["copilot", "opencode"] if target == "all" else [target]


# Per-target discovery paths (relative to the workspace root) where each tool
# actually loads agents and instructions from.
#   copilot/VS Code: .github/agents/*.md      + .github/copilot-instructions.md
#   opencode:        .opencode/agents/*.md    + AGENTS.md (project root)
_AGENT_DIRS = {
    "copilot": (".github", "agents"),
    "opencode": (".opencode", "agents"),
}
_INSTRUCTION_PATHS = {
    "copilot": (".github", "copilot-instructions.md"),
    "opencode": ("AGENTS.md",),
}


def _agents_dir(target_root: Path, tool: str) -> Path:
    return target_root.joinpath(*_AGENT_DIRS[tool])


def _instructions_path(target_root: Path, tool: str) -> Path:
    return target_root.joinpath(*_INSTRUCTION_PATHS[tool])


def _write_if_absent(path: Path, content: str) -> bool:
    """Write ``content`` to ``path`` only if it does not already exist.

    Returns True if written, False if skipped. Used for instruction files
    (``AGENTS.md`` / ``copilot-instructions.md``) which may carry user content
    and must never be clobbered.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def _render_and_write(target: Path, config: dict, env) -> None:
    """Render templates and write them to each target's discovery paths.

    Carter-owned agent files (``carter-*``) are always (re)written so that
    ``carter update`` refreshes them. Instruction files are written only when
    absent (skip-if-exists), so user edits to ``AGENTS.md`` /
    ``copilot-instructions.md`` are preserved.
    """
    tools = _resolve_targets(config.get("target", "copilot"))
    agents = render_agents(config, env)
    instructions_content = render_instructions(config, env)["copilot-instructions.md"]

    for tool in tools:
        write_rendered_files(agents, _agents_dir(target, tool))
        _write_if_absent(_instructions_path(target, tool), instructions_content)



@main.command(
    "ops",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        "help_option_names": [],
    },
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def ops(args: tuple[str, ...]):
    """Run a carter-ops operation (deterministic executor).

    All arguments are passed through to the carter-ops CLI, e.g.:

        carter ops --list
        carter ops audit --operation git-flow --result success
        carter ops git-flow --branch feature/x --message "feat: x" --dry-run
    """
    from carter.ops.carter_ops import main as ops_main

    raise SystemExit(ops_main(list(args)))


if __name__ == "__main__":
    main()
