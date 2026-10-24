"""Carter CLI — workspace scaffolding and management commands."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import click
import yaml
from jinja2 import Environment

from carter.config import (
    PROFILES,
    ConfigError,
    _validate_agent_suffix,
    _validate_docs_language,
    generate_default_config,
    load_config,
    parse_policy_comment,
    resolve_targets,
)
from carter.plans import validate_checkpoint, validate_plans_dir
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
from carter.state import StateError, add_to_gitignore, commit_state, init_workspace


@click.group()
@click.version_option(package_name="carter-ai")
def main() -> None:
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
    "--mcp-servers",
    "mcp_servers",
    default=None,
    help="Comma-separated subset of MCP servers to install (e.g. 'github,terraform'). "
    "Default: all. Only meaningful with --mcp.",
)
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
    mcp_servers: str | None,
    bot_name: str,
    uninstall_flag: bool,
    base_dir: Path | None,
    quiet: bool,
    verbose: bool,
    debug: bool,
) -> None:
    """Install Carter agents, skills, and MCP servers system-wide (~/.copilot/)."""
    from carter.install.mcp import MCP_SERVERS
    from carter.installer import run as run_install

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

    run_install(
        target=target,
        mcp=mcp,
        bot_name=bot_name,
        uninstall_flag=uninstall_flag,
        base_dir=base_dir,
        verbosity=verbosity,
        mcp_servers=servers,
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
    target_tool: str | None,
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
    if target_tool is not None:
        config["target"] = target_tool
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


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, help="Preview changes without writing")
def update(target_dir: str, dry_run: bool) -> None:
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
        tools = resolve_targets(config.get("target", "copilot"))
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
    click.echo(f"ℹ  {policy_notice(config)}")
    click.echo("Templates re-rendered from carter.yaml")


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--accept-degraded",
    is_flag=True,
    default=False,
    help="Acknowledge that a strict policy degrades to advisory on a "
    "non-enforcing target (e.g. copilot). Required for strict on such targets.",
)
def check(target_dir: str, accept_degraded: bool) -> None:
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

    # Check agent and instruction files exist in each target's discovery path,
    # collecting each role's parsed frontmatter for the policy lint as we go.
    installed: dict[str, dict] = {}
    for tool in resolve_targets(config.get("target", "copilot")):
        agents_dir = _agents_dir(target, tool)
        for agent_name in config["agents"]:
            agent_file = agents_dir / agent_filename(agent_name, config)
            if not agent_file.exists():
                errors.append(f"Missing agent file: {agent_file.relative_to(target)}")
                continue
            if agent_name not in installed:
                parsed = _parse_agent_frontmatter(agent_file.read_text())
                if parsed is not None:
                    installed[agent_name] = parsed

        instructions_file = _instructions_path(target, tool)
        if not instructions_file.exists():
            errors.append(f"Missing instructions: {instructions_file.relative_to(target)}")

    # Check knowledge files
    knowledge_dir = target / ".carter" / "knowledge"
    for filename in ["lessons-learned.md", "gotchas.md", "tools.md", "decisions.md", "patterns.md"]:
        if not (knowledge_dir / filename).exists():
            errors.append(f"Missing knowledge file: .carter/knowledge/{filename}")

    # Validate plan frontmatter contract; thresholds from config
    plans_root = target / ".carter" / "state" / "plans"
    errors.extend(validate_plans_dir(plans_root, config.get("plans")))

    # Validate the session checkpoint cursor (absent is fine); cross-check that
    # its active_plan resolves to a real plan under active/.
    checkpoint = target / ".carter" / "state" / "sessions" / "checkpoint.md"
    errors.extend(validate_checkpoint(checkpoint, plans_root))

    # Lint emitted policy frontmatter against the declared model.
    policy_errors, policy_warnings = lint_policy(config, installed, accept_degraded=accept_degraded)
    errors.extend(policy_errors)

    if errors:
        click.echo("Workspace issues found:", err=True)
        for error in errors:
            click.echo(f"  ✗ {error}", err=True)
        raise SystemExit(1)

    for warning in policy_warnings:
        click.echo(f"⚠  {warning}", err=True)

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


def _parse_agent_frontmatter(text: str) -> dict | None:
    """Parse the leading YAML frontmatter from an agent markdown file.

    Returns the parsed mapping, or ``None`` if the file has no parseable
    ``---``-delimited frontmatter block.
    """
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    # The advisory policy block lives in a `carter:policy` HTML comment after the
    # frontmatter (kept off the wire, ADR-0005); re-inject it under `policy` so the
    # lint sees the same shape it always did.
    policy = parse_policy_comment(text)
    if policy is not None:
        data["policy"] = policy
    return data


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


def _render_and_write(target: Path, config: dict, env: Environment) -> None:
    """Render templates and write them to each target's discovery paths.

    Carter-owned agent files (``carter-*``) are always (re)written so that
    ``carter update`` refreshes them. Instruction files are written only when
    absent (skip-if-exists), so user edits to ``AGENTS.md`` /
    ``copilot-instructions.md`` are preserved.
    """
    tools = resolve_targets(config.get("target", "copilot"))
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
def ops(args: tuple[str, ...]) -> None:
    """Carter-ops audit ledger and config helper (used by the carter-ops skill).

    All arguments are passed through to the carter-ops CLI, e.g.:

        carter ops audit --operation git-flow --result success
        carter ops policy-override --category remote-write --action "git push" --tier native-ask
        carter ops config --emit
    """
    from carter.ops.carter_ops import main as ops_main

    raise SystemExit(ops_main(list(args)))


if __name__ == "__main__":
    main()
