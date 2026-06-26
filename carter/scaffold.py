"""Jinja2 template rendering engine for Carter workspaces."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from carter.config import (
    ConfigError,
    _emit_level,
    _gates_for,
    effective_allowlist,
    policy_frontmatter,
    policy_gate_table,
    policy_native_keys,
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
    # Strictness-policy emitters used by base_agent.md.j2 (RFC-0002 / ADR-0005).
    env.globals["policy_frontmatter"] = policy_frontmatter
    env.globals["policy_gate_table"] = policy_gate_table
    return env


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

    Flags the redaction gap: if the narrator is enabled but ``redaction.enabled``
    is false *at* ``loose``, the scaffolded narrator carries no redaction rules
    even though Maestro routes external-facing content to it. At ``guarded`` and
    ``strict`` the redaction pass is forced regardless (the narrator template
    renders the rules), so the gap does not exist there — the policy lint instead
    surfaces the ``redaction.enabled: false`` contradiction (Q16).
    """
    warnings: list[str] = []
    narrator_on = "narrator" in config.get("agents", [])
    redaction_on = bool(config.get("redaction", {}).get("enabled", False))
    level = (config.get("policy") or {}).get("level", "loose")
    if narrator_on and not redaction_on and level == "loose":
        warnings.append(
            "narrator is enabled but redaction.enabled is false — the scaffolded "
            "narrator will have NO redaction rules, yet Maestro still routes "
            "external-facing content to it. Enable redaction or remove narrator "
            "from agents."
        )
    return warnings


def policy_notice(config: dict[str, Any]) -> str | None:
    """The 'you're guarded now' migration notice, surfaced at init/update (P2).

    Returns a one-line message when the active strictness level enforces gates
    (`guarded` or `strict`), or ``None`` for `loose` (no behaviour change, so no
    notice). Q6: new installs default to `guarded`; an existing/omitted policy
    stays `loose` and stays quiet.
    """
    level = (config.get("policy") or {}).get("level", "loose")
    if level == "loose":
        return None
    return (
        f"Strictness policy is '{level}': remote-write, infra-mutate, "
        "secret-access, destructive, and external-publish actions are now gated "
        "per the risk taxonomy (see the maestro policy table). Set "
        "policy.level: loose in carter.yaml to restore advisory-only behaviour."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Policy lint (RFC-0002 / ADR-0005, P3)
# ──────────────────────────────────────────────────────────────────────────────
# `carter check` runs `lint_policy` to verify the emitted agent frontmatter still
# matches the declared policy model (the per-agent allowlist x the active level's
# gate map). This is a *config* lint: it proves what Carter wrote equals what Carter
# declared. It deliberately CANNOT verify runtime denial — that a platform actually
# refuses a gated action at execution time is out of scope (Q17); only an enforcing
# target does that, and only at runtime.

# Whether a target natively enforces per-category gates. OpenCode's `permission`
# block gates/denies per category at runtime. The `copilot` target spans two
# surfaces (ADR-0010 D8 re-eval): Copilot CLI `hooks` preToolUse *can* now
# deterministically block, but VS-Code-declarative custom agents still have no
# per-category gate. Since `copilot` covers both, it resolves to the weaker member
# — non-enforcing — so a strict policy honestly degrades to advisory there and the
# hard-ack fires. Flipping it to True would over-promise on the VS Code surface.
_TARGET_ENFORCES_GATES: dict[str, bool] = {"opencode": True, "copilot": False}


def _resolve_policy_targets(target: str) -> list[str]:
    """Resolve a config ``target`` to concrete tool targets (``all`` = both)."""
    return ["copilot", "opencode"] if target == "all" else [target]


def lint_policy(
    config: dict[str, Any],
    installed: dict[str, dict[str, Any]],
    *,
    accept_degraded: bool = False,
) -> tuple[list[str], list[str]]:
    """Lint emitted agent frontmatter against the declared strictness policy.

    ``installed`` maps each role to its parsed agent-file frontmatter (the dict
    carrying the emitted ``policy`` block). For every installed role this recomputes
    the expected allowlist + gate map from the model and reports drift as an error;
    a role absent from ``installed`` is not lint's concern (missing files are handled
    by ``carter check`` itself). It also enforces the strict-on-non-enforcing-target
    acknowledgement (Q15, fail-closed) and the redaction contradiction (Q16).

    Returns ``(errors, warnings)``. Scope notes:

    - Per-agent MCP scope is read from frontmatter only; global MCP server wiring is
      ``configure_mcp_servers``' job and is NOT linted here (N2 — no false
      "server not wired" warning).
    - Runtime denial is out of scope (Q17): this verifies that emitted config matches
      declared policy, not that the platform refuses a gated action at runtime.
    """
    errors: list[str] = []
    warnings: list[str] = []

    policy = config.get("policy") or {}
    level = policy.get("level", "loose")
    emit_level = _emit_level(level)
    allowlist = effective_allowlist(config)
    overrides = policy.get("overrides")

    # Drift: emitted allow/gates + native keys must match the declared model.
    for role, frontmatter in installed.items():
        emitted = (frontmatter or {}).get("policy")
        if not emitted:
            errors.append(f"{role}: agent frontmatter is missing the policy block")
            continue
        expected_allow = [cat for cat, on in sorted(allowlist.get(role, {}).items()) if on]
        expected_gates = _gates_for(expected_allow, emit_level, overrides)
        if emitted.get("allow") != expected_allow:
            errors.append(
                f"{role}: emitted allow {emitted.get('allow')} drifted from "
                f"declared allowlist {expected_allow}"
            )
        if emitted.get("gates") != expected_gates:
            errors.append(
                f"{role}: emitted gates {emitted.get('gates')} drifted from "
                f"declared gate map {expected_gates}"
            )
        # The native enforcement keys (OpenCode `permission`, copilot `tools`) are
        # the ACTUALLY-enforced surface — drift here matters more than the
        # advisory policy block, so lint them against the same model.
        expected_native = policy_native_keys(config, role)
        for key in ("tools", "permission"):
            if (key in expected_native) != (key in (frontmatter or {})):
                errors.append(
                    f"{role}: emitted {key} presence drifted from the declared target policy"
                )
            elif key in expected_native and (frontmatter or {}).get(key) != expected_native[key]:
                errors.append(
                    f"{role}: emitted {key} {(frontmatter or {}).get(key)} drifted "
                    f"from declared {expected_native[key]}"
                )

    # Q15 HARD ACK: strict on a non-enforcing target must be explicitly accepted.
    if level == "strict":
        non_enforcing = [
            t
            for t in _resolve_policy_targets(config.get("target", "copilot"))
            if not _TARGET_ENFORCES_GATES.get(t, False)
        ]
        if non_enforcing:
            targets = ", ".join(non_enforcing)
            if accept_degraded:
                warnings.append(
                    f"strict level degrades to advisory on {targets} "
                    "(acknowledged via --accept-degraded)"
                )
            else:
                errors.append(
                    f"strict level on a non-enforcing target ({targets}) requires "
                    "explicit --accept-degraded"
                )

    # Q16 redaction WARN: guarded|strict forces a redaction pass at runtime, so a
    # disabled redaction config is a contradiction worth surfacing.
    if level in ("guarded", "strict") and not (config.get("redaction") or {}).get("enabled", False):
        warnings.append(
            f"{level} forces a redaction pass but redaction.enabled is false — "
            "narrator renders with no redaction rules; strict|guarded will force "
            "the pass at runtime"
        )

    return errors, warnings


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
