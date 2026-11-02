"""Jinja2 template rendering engine for Carter workspaces."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from carter.aplus.handoff import OWN_TERMINAL
from carter.config import (
    PRIMARY_ROLE,
    V1_AGENT_KEYS,
    ConfigError,
    policy_frontmatter,
    policy_gate_table,
    policy_native_keys,
    resolve_model,
)
from carter.resources import templates_dir

TEMPLATES_DIR = templates_dir()

# Valid agent names: lowercase letters, digits, hyphens only
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def create_env(templates_dir: Path = TEMPLATES_DIR) -> Environment:
    """Create a Jinja2 environment configured for Carter templates."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    # Strictness-policy emitters used by base_agent.md.j2.
    env.globals["policy_frontmatter"] = policy_frontmatter
    env.globals["policy_gate_table"] = policy_gate_table
    env.globals["docs_language_phrase"] = docs_language_phrase
    # The one sentence that tells the user where pushing happens (handoff.OWN_TERMINAL).
    env.globals["own_terminal"] = OWN_TERMINAL
    # Only the primary orchestrator dispatches (flat one-level chain), so only it
    # renders the <agents> roster.
    env.globals["primary_role"] = PRIMARY_ROLE
    return env


def docs_language_phrase(config: dict[str, Any]) -> str:
    """How templates name the language for Carter's internal docs.

    A workspace render names its ``docs_language``; a global render (no workspace,
    ``docs_language`` unset) points at the workspace setting with an English default.
    """
    tag = config.get("docs_language")
    if tag:
        return f"`{tag}` (`docs_language`)"
    return (
        "the workspace `docs_language` from `.carter/carter.yaml` "
        "(English if unset, unless the user asks for another language)"
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


def policy_notice(config: dict[str, Any]) -> str:
    """The 'you're guarded now' notice, surfaced at init/update.

    Both shipped levels (``guarded``/``strict``) enforce gates, so the notice always
    fires, naming the active level and the gated categories.
    """
    level = (config.get("policy") or {}).get("level", "guarded")
    return (
        f"Strictness policy is '{level}': remote-write and dangerous "
        "(infra-mutate / destructive) actions are gated per the risk taxonomy "
        "(see the maestro policy table)."
    )


def model_advisory(config: dict[str, Any]) -> str:
    """The model advisory `carter check` always prints (never empty).

    OpenCode ignores a pinned model your provider lacks, so name each pin.
    """
    pins = ", ".join(f"{role} → {resolve_model(config, role)}" for role in config.get("agents", []))
    return (
        f"Model pins: {pins}. Carter cannot verify your OpenCode provider "
        "subscription includes them."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Policy lint
# ──────────────────────────────────────────────────────────────────────────────
# `carter check` runs `lint_policy` to verify each emitted agent's `permissions:` and
# `model` still equal what carter.yaml generates, and that no V1 key is present. This
# is a *config* lint: it proves what Carter wrote equals what Carter declared; it
# cannot verify runtime denial.


def lint_policy(config: dict[str, Any], installed: dict[str, dict[str, Any]]) -> list[str]:
    """Lint emitted agent frontmatter against carter.yaml; returns the errors.

    ``installed`` maps each role to its parsed agent-file frontmatter. A role absent
    from ``installed`` is not lint's concern (missing files are reported by
    ``carter check`` itself). Rule order matters (last match wins), so the emitted
    ``permissions:`` must equal the expected list exactly.
    """
    errors: list[str] = []
    for role, frontmatter in installed.items():
        fm = frontmatter or {}
        v1 = [key for key in V1_AGENT_KEYS if key in fm]
        if v1:
            errors.append(
                f"{role}: V1 frontmatter key(s) {v1} present — OpenCode ignores them "
                "next to 'permissions'; run `carter update`"
            )
        expected = policy_native_keys(config, role)
        for key in ("permissions", "model"):
            if key not in fm:
                errors.append(f"{role}: emitted frontmatter is missing '{key}'")
            elif fm[key] != expected.get(key):
                errors.append(
                    f"{role}: emitted {key} drifted from what carter.yaml generates "
                    "(run `carter update`)"
                )
    return errors


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
    assert isinstance(env.loader, FileSystemLoader)  # always created via create_env
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
    template = env.get_template("instructions/AGENTS.md.j2")
    content = template.render(config=config)
    content = _apply_agent_suffix(content, config["agents"], _suffix_token(config))
    return {"AGENTS.md": content}


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
