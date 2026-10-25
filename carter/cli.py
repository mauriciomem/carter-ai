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
)
from carter.harness import validate_agents
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
    mcp: bool,
    mcp_servers: str | None,
    bot_name: str,
    uninstall_flag: bool,
    base_dir: Path | None,
    quiet: bool,
    verbose: bool,
    debug: bool,
) -> None:
    """Install Carter agents, skills, and MCP servers for OpenCode (>= 2.1)."""
    from carter.install.mcp import MCP_SERVERS
    from carter.install.orchestrator import run as run_install
    from carter.install.prereqs import PrerequisiteError

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
        run_install(
            mcp=mcp,
            bot_name=bot_name,
            uninstall_flag=uninstall_flag,
            base_dir=base_dir,
            verbosity=verbosity,
            mcp_servers=servers,
        )
    except PrerequisiteError as exc:
        raise click.ClickException(f"{exc} Nothing was installed.") from exc


@main.command()
@click.option(
    "--legacy",
    is_flag=True,
    help="Remove Copilot/VS Code files an earlier Carter install listed in its manifest.",
)
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override install base directory (for testing).",
)
def uninstall(legacy: bool, base_dir: Path | None) -> None:
    """Remove the Carter OpenCode install, or with --legacy the old Copilot leftovers."""
    if legacy:
        from carter.install.legacy import uninstall_legacy

        uninstall_legacy(base_dir)
    else:
        from carter.install.uninstall import uninstall as run_uninstall

        run_uninstall(base_dir)


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


@main.command()
@click.argument("target_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--no-harness",
    is_flag=True,
    help="Skip the `opencode debug agents` harness validation step.",
)
def check(target_dir: str, no_harness: bool) -> None:
    """Validate workspace integrity and that OpenCode loads the Carter agents."""
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

    # Check agent and instruction files exist in OpenCode's discovery paths,
    # collecting each role's parsed frontmatter for the policy lint as we go.
    installed: dict[str, dict] = {}
    agents_dir = _agents_dir(target)
    for agent_name in config["agents"]:
        agent_file = agents_dir / agent_filename(agent_name, config)
        if not agent_file.exists():
            errors.append(f"Missing agent file: {agent_file.relative_to(target)}")
            continue
        parsed = _parse_agent_frontmatter(agent_file.read_text())
        if parsed is None:
            errors.append(f"Unparseable frontmatter: {agent_file.relative_to(target)}")
        else:
            installed[agent_name] = parsed

    instructions_file = _instructions_path(target)
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

    # Lint emitted `permissions:`/`model` against what carter.yaml generates.
    errors.extend(lint_policy(config, installed))

    # Harness validation: OpenCode must actually load every agent.
    if not no_harness:
        expected: dict[str, list | None] = {}
        for role in config["agents"]:
            if not (agents_dir / agent_filename(role, config)).exists():
                continue  # already reported as a missing file
            perms = installed.get(role, {}).get("permissions")
            expected[Path(agent_filename(role, config)).stem] = (
                perms if isinstance(perms, list) else None
            )
        harness_result = validate_agents(target, expected)
        if harness_result.warning:
            click.echo(f"⚠  {harness_result.warning}", err=True)
        errors.extend(harness_result.errors)
        if harness_result.status == "ok":
            click.echo(f"OpenCode loaded all {len(expected)} Carter agents")

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
_AGENT_DIR = (".opencode", "agents")
_INSTRUCTION_PATH = ("AGENTS.md",)


def _agents_dir(target_root: Path) -> Path:
    return target_root.joinpath(*_AGENT_DIR)


def _instructions_path(target_root: Path) -> Path:
    return target_root.joinpath(*_INSTRUCTION_PATH)


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
    return data


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
        carter ops policy-override --category remote-write --action "git push" --tier native-ask
        carter ops config --emit
    """
    from carter.ops.carter_ops import main as ops_main

    raise SystemExit(ops_main(list(args)))


if __name__ == "__main__":
    main()
