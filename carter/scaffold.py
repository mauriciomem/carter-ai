"""Jinja2 template rendering engine for Carter workspaces."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from carter.config import (
    PRIMARY_ROLE,
    ConfigError,
    _emit_level,
    _gates_for,
    dispatch_specialists,
    effective_allowlist,
    policy_comment,
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
    env.globals["policy_comment"] = policy_comment
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

    Both shipped strictness levels **force** the narrator's redaction pass — the
    rule-less-narrator gap that this warning once flagged at a since-dropped advisory
    level can no longer occur. A ``redaction.enabled: false`` contradiction at an
    enforcing level is surfaced by the policy lint instead, not here. Kept as a seam
    so future non-fatal config warnings have a home.
    """
    return []


def policy_notice(config: dict[str, Any]) -> str | None:
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
    """The required unverifiable-model advisory `carter check` always prints.

    Carter pins a per-agent `model:` but cannot verify the user's Copilot/OpenCode
    subscription actually includes it — an unavailable model would be silently ignored
    frontmatter (a broken agent). So it emits the pin anyway and names every agent's
    pinned model with the can't-verify caveat. Always returns a non-empty string.
    """
    pins = ", ".join(f"{role} → {resolve_model(config, role)}" for role in config.get("agents", []))
    return (
        f"Agents pin these models: {pins}. Carter cannot verify your "
        "Copilot/OpenCode subscription includes them — an unavailable model is "
        "silently ignored at load. Effort is global (`--effort high`, per-session "
        "overridable); Carter emits no per-agent effort or temperature."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Policy lint
# ──────────────────────────────────────────────────────────────────────────────
# `carter check` runs `lint_policy` to verify the emitted agent frontmatter still
# matches the declared policy model (the per-agent allowlist x the active level's
# gate map). This is a *config* lint: it proves what Carter wrote equals what Carter
# declared. It deliberately CANNOT verify runtime denial — that a platform actually
# refuses a gated action at execution time is out of scope; only an enforcing
# target does that, and only at runtime.

# Whether a target natively enforces per-category gates. OpenCode's `permission`
# block gates/denies per category at runtime. The `copilot` target spans two
# surfaces: Copilot CLI `hooks` preToolUse *can* now
# deterministically block, but VS-Code-declarative custom agents still have no
# per-category gate. Since `copilot` covers both, it resolves to the weaker member
# — non-enforcing — so a strict policy honestly degrades to advisory there and the
# hard-ack fires. Flipping it to True would over-promise on the VS Code surface.
_TARGET_ENFORCES_GATES: dict[str, bool] = {"opencode": True, "copilot": False}


def _resolve_policy_targets(target: str) -> list[str]:
    """Resolve a config ``target`` to concrete tool targets (``all`` = both)."""
    return ["copilot", "opencode"] if target == "all" else [target]


def _is_failopen_entry(entry: str) -> bool:
    """A dispatch allowlist entry that breaks deny-by-default: ``'*'`` or any glob."""
    return entry == "*" or "*" in entry


def _lint_dispatch_allowlist(config: dict[str, Any], primary_fm: dict[str, Any]) -> list[str]:
    """Fail-closed lint of the primary's native dispatch allowlist.

    Errors (never warns) when the maestro's emitted ``agents:`` (copilot) or
    ``permission.task`` (opencode) is ``'*'``, contains a glob, or is absent. Compares
    against the expected explicit per-specialist list so a *narrowed/tampered* list is
    also caught. Per target: copilot validates ``agents:``; opencode ``permission.task``.
    """
    errors: list[str] = []
    expected = dispatch_specialists(config)
    targets = _resolve_policy_targets(config.get("target", "copilot"))

    if "copilot" in targets:
        agents = primary_fm.get("agents")
        if agents is None:
            errors.append(
                f"{PRIMARY_ROLE}: native dispatch allowlist 'agents:' is absent "
                "(fail-closed: the primary must emit an explicit per-specialist list)"
            )
        elif any(_is_failopen_entry(a) for a in agents):
            errors.append(
                f"{PRIMARY_ROLE}: 'agents:' contains '*'/a glob — a failure-open "
                "dispatch boundary; it must be an explicit per-specialist list"
            )
        elif agents != expected:
            errors.append(
                f"{PRIMARY_ROLE}: emitted 'agents:' {agents} drifted from the "
                f"declared dispatch allowlist {expected}"
            )

    if "opencode" in targets:
        task = (primary_fm.get("permission") or {}).get("task")
        if not task:
            errors.append(
                f"{PRIMARY_ROLE}: native dispatch 'permission.task' is absent "
                "(fail-closed: the primary must emit '*': deny + explicit allows)"
            )
        elif task.get("*") != "deny" or any(_is_failopen_entry(k) for k in task if k != "*"):
            errors.append(
                f"{PRIMARY_ROLE}: 'permission.task' must be '*': deny + an explicit "
                "per-specialist allow — found '*'/a glob (failure-open)"
            )
        else:
            expected_task = {"*": "deny", **dict.fromkeys(expected, "allow")}
            if task != expected_task:
                errors.append(
                    f"{PRIMARY_ROLE}: emitted 'permission.task' {task} drifted from "
                    f"the declared dispatch allowlist {expected_task}"
                )
    return errors


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
    acknowledgement (fail-closed) and the redaction contradiction.

    Returns ``(errors, warnings)``. Scope notes:

    - Per-agent MCP scope is read from frontmatter only; global MCP server wiring is
      ``configure_mcp_servers``' job and is NOT linted here (no false
      "server not wired" warning).
    - Runtime denial is out of scope: this verifies that emitted config matches
      declared policy, not that the platform refuses a gated action at runtime.
    """
    errors: list[str] = []
    warnings: list[str] = []

    policy = config.get("policy") or {}
    level = policy.get("level", "guarded")
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
        for key in ("tools", "permission", "model"):
            if (key in expected_native) != (key in (frontmatter or {})):
                errors.append(
                    f"{role}: emitted {key} presence drifted from the declared target policy"
                )
            elif key in expected_native and (frontmatter or {}).get(key) != expected_native[key]:
                errors.append(
                    f"{role}: emitted {key} {(frontmatter or {}).get(key)} drifted "
                    f"from declared {expected_native[key]}"
                )

    # FAIL-CLOSED DISPATCH LINT: the primary's native dispatch allowlist is a
    # security boundary. A `'*'`, a glob, or an absent `agents:`/`permission.task` on
    # the maestro is a build-breaking ERROR (never a warning) — `'*'` lets the maestro
    # delegate to any workspace agent (failure-open), and a `carter-*` glob auto-trusts
    # any future `carter-*` agent. Only checked when the primary is installed and the
    # target emits that key (copilot → `agents:`; opencode → `permission.task`).
    primary_fm = installed.get(PRIMARY_ROLE)
    if primary_fm is not None:
        errors.extend(_lint_dispatch_allowlist(config, primary_fm))

    # HARD ACK: strict on a non-enforcing target must be explicitly accepted.
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

    # REDACTION WARN: guarded|strict forces a redaction pass at runtime, so a
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
