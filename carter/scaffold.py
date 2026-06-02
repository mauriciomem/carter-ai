"""Jinja2 template rendering engine for Carter workspaces."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from carter.config import ConfigError
from carter.resources import templates_dir

TEMPLATES_DIR = templates_dir()

# Valid agent names: lowercase letters, digits, hyphens only
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def create_env(templates_dir: Path = TEMPLATES_DIR) -> Environment:
    """Create a Jinja2 environment configured for Carter templates."""
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _available_agents(templates_dir: Path) -> list[str]:
    """Discover available agent names from template files on disk."""
    agents_dir = templates_dir / "agents"
    if not agents_dir.is_dir():
        return []
    return sorted(
        p.stem.removeprefix("carter-").removesuffix(".md")
        for p in agents_dir.glob("carter-*.md.j2")
    )


def _validate_agents(agent_names: list[str], templates_dir: Path) -> None:
    """Validate agent names: format check + template existence."""
    available = _available_agents(templates_dir)

    for name in agent_names:
        if not name or not _AGENT_NAME_RE.match(name):
            raise ConfigError(
                f"Invalid agent name: '{name}'. "
                f"Names must be lowercase alphanumeric with hyphens. "
                f"Available agents: {', '.join(available)}"
            )
        if name not in available:
            raise ConfigError(
                f"Unknown agent: '{name}'. "
                f"No template found at templates/agents/carter-{name}.md.j2. "
                f"Available agents: {', '.join(available)}"
            )


def render_agents(config: dict[str, Any], env: Environment) -> dict[str, str]:
    """Render all configured agent templates.

    Returns a dict of {filename: rendered_content}.
    Raises ConfigError if any agent name is invalid or has no template.
    """
    templates_dir = Path(env.loader.searchpath[0])
    _validate_agents(config["agents"], templates_dir)

    results = {}
    for agent_name in config["agents"]:
        template_path = f"agents/carter-{agent_name}.md.j2"
        template = env.get_template(template_path)
        content = template.render(config=config, agent=agent_name)
        results[f"carter-{agent_name}.md"] = content
    return results


def render_instructions(config: dict[str, Any], env: Environment) -> dict[str, str]:
    """Render global instruction templates.

    Returns a dict of {filename: rendered_content}.
    """
    results = {}
    template = env.get_template("instructions/copilot-instructions.md.j2")
    results["copilot-instructions.md"] = template.render(config=config)
    return results


def write_rendered_files(
    files: dict[str, str],
    output_dir: Path,
) -> list[Path]:
    """Write rendered content to disk. Returns list of written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content in files.items():
        path = output_dir / filename
        path.write_text(content)
        written.append(path)
    return written
