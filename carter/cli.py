"""Carter CLI — workspace scaffolding and management commands."""
from __future__ import annotations

from pathlib import Path

import click

from carter.config import ConfigError, generate_default_config, load_config, write_config
from carter.scaffold import create_env, render_agents, render_instructions, write_rendered_files
from carter.state import add_to_gitignore, init_workspace


@click.group()
@click.version_option(package_name="carter-ai")
def main():
    """Carter AI — workspace scaffolding and management."""


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--single", is_flag=True, help="Single-repo mode (default: umbrella)")
@click.option("--no-git-state", is_flag=True, help="Skip git init for state dirs")
@click.option("--name", default=None, help="Workspace name (default: directory name)")
def init(target_dir: str, single: bool, no_git_state: bool, name: str | None):
    """Initialize a Carter workspace."""
    target = Path(target_dir).resolve()
    workspace_name = name or target.name
    mode = "single" if single else "umbrella"

    # Generate default config
    config = generate_default_config(workspace_name=workspace_name, mode=mode)
    config["state"]["git_tracked"] = not no_git_state

    # Create .carter/ structure
    carter_dir = init_workspace(
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
        instructions = render_instructions(config, env)
        click.echo("Would render:")
        for name in sorted(agents):
            click.echo(f"  agents/{name}")
        for name in sorted(instructions):
            click.echo(f"  instructions/{name}")
        return

    _render_and_write(target, config, env)
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

    # Check agent files exist
    agents_dir = target / "agents"
    for agent_name in config["agents"]:
        agent_file = agents_dir / f"carter-{agent_name}.md"
        if not agent_file.exists():
            errors.append(f"Missing agent file: agents/carter-{agent_name}.md")

    # Check instructions
    instructions_dir = target / "instructions"
    instructions_file = instructions_dir / "copilot-instructions.md"
    if not instructions_file.exists():
        errors.append("Missing: instructions/copilot-instructions.md")

    # Check knowledge files
    knowledge_dir = target / ".carter" / "knowledge"
    for filename in ["lessons-learned.md", "gotchas.md", "tools.md", "decisions.md", "patterns.md"]:
        if not (knowledge_dir / filename).exists():
            errors.append(f"Missing knowledge file: .carter/knowledge/{filename}")

    if errors:
        click.echo("Workspace issues found:", err=True)
        for error in errors:
            click.echo(f"  ✗ {error}", err=True)
        raise SystemExit(1)

    click.echo("Workspace OK")


def _render_and_write(target: Path, config: dict, env) -> None:
    """Render all templates and write to disk."""
    agents = render_agents(config, env)
    write_rendered_files(agents, target / "agents")

    instructions = render_instructions(config, env)
    write_rendered_files(instructions, target / "instructions")
