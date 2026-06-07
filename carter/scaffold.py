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


def _suffix_token(config: dict[str, Any]) -> str:
    """Return the agent-name suffix token, e.g. ``-local`` or ``""`` (none).

    Driven by ``config["agent_suffix"]`` (validated by ``carter.config``).
    """
    raw = (config.get("agent_suffix") or "").strip()
    return f"-{raw}" if raw else ""


def agent_filename(role: str, config: dict[str, Any]) -> str:
    """Return the rendered agent filename for a role, honoring ``agent_suffix``."""
    return f"carter-{role}{_suffix_token(config)}.md"


def config_warnings(config: dict[str, Any]) -> list[str]:
    """Return non-fatal configuration warnings for a workspace config.

    Currently flags the redaction gap: if the narrator agent is enabled but
    ``redaction.enabled`` is false, the scaffolded narrator carries no redaction
    rules even though it is the agent Maestro routes external-facing content to.
    """
    warnings: list[str] = []
    narrator_on = "narrator" in config.get("agents", [])
    redaction_on = bool(config.get("redaction", {}).get("enabled", False))
    if narrator_on and not redaction_on:
        warnings.append(
            "narrator is enabled but redaction.enabled is false — the scaffolded "
            "narrator will have NO redaction rules, yet Maestro still routes "
            "external-facing content to it. Enable redaction or remove narrator "
            "from agents."
        )
    return warnings


def _apply_agent_suffix(content: str, roles: list[str], suffix: str) -> str:
    """Append ``suffix`` to every ``carter-<role>`` reference in rendered output.

    Scoped strictly to the configured agent ``roles`` so skill names
    (e.g. ``carter-ops``, ``carter-docs``, ``carter-pipeline``) are never
    rewritten. Idempotent: a negative lookahead avoids double-suffixing.
    """
    if not suffix:
        return content
    for role in roles:
        content = re.sub(
            rf"\bcarter-{re.escape(role)}\b(?!{re.escape(suffix)})",
            f"carter-{role}{suffix}",
            content,
        )
    return content


def render_agents(config: dict[str, Any], env: Environment) -> dict[str, str]:
    """Render all configured agent templates.

    Returns a dict of {filename: rendered_content}. Filenames and internal
    ``carter-<role>`` references honor ``config["agent_suffix"]`` so workspace
    agents stay distinct from globally installed ones.
    Raises ConfigError if any agent name is invalid or has no template.
    """
    templates_dir = Path(env.loader.searchpath[0])
    _validate_agents(config["agents"], templates_dir)

    suffix = _suffix_token(config)
    roles = config["agents"]
    results = {}
    for agent_name in config["agents"]:
        template_path = f"agents/carter-{agent_name}.md.j2"
        template = env.get_template(template_path)
        content = template.render(config=config, agent=agent_name)
        content = _apply_agent_suffix(content, roles, suffix)
        results[f"carter-{agent_name}{suffix}.md"] = content
    return results


def render_instructions(config: dict[str, Any], env: Environment) -> dict[str, str]:
    """Render global instruction templates.

    Returns a dict of {filename: rendered_content}. Agent references inside the
    instructions honor ``agent_suffix`` (the filename itself is not suffixed).
    """
    template = env.get_template("instructions/copilot-instructions.md.j2")
    content = template.render(config=config)
    content = _apply_agent_suffix(content, config["agents"], _suffix_token(config))
    return {"copilot-instructions.md": content}


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
