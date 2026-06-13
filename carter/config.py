"""Configuration loading and schema validation for carter.yaml."""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

REQUIRED_KEYS = {"version", "workspace", "identity", "agents"}

# agent_suffix becomes part of scaffolded agent filenames/names
# (e.g. carter-engineer-local). Lowercase alphanumeric + hyphen, or empty.
_AGENT_SUFFIX_RE = re.compile(r"^[a-z0-9-]*$")

DEFAULT_CONFIG: dict[str, Any] = {
    "version": "2",
    "workspace": {
        "name": "my-workspace",
        "description": "",
        "mode": "umbrella",
    },
    "identity": {
        "git_account": "",
        "git_org": None,
        "bot_name": "carter-bot",
        "bot_email": "carter-bot@users.noreply.github.com",
    },
    "personality": {
        "skepticism": "scaled",
        "style": "reviewer",
    },
    "agents": [
        "maestro",
        "architect",
        "engineer",
        "devops",
        "pm",
        "learner",
        "narrator",
    ],
    # Suffix distinguishing workspace-scaffolded agents from globally installed
    # ones (e.g. carter-engineer-local). Empty string = same names as global.
    "agent_suffix": "local",
    "quality_gate": {
        "enabled": True,
        "max_iterations": 2,
        "trigger": "user-initiated",
    },
    "redaction": {
        "enabled": True,
        "categories": [
            "secrets",
            "internal_urls",
            "security_incidents",
            "pii",
            "financials",
            "employee_data",
            "infra_ids",
        ],
    },
    "tdd": {
        "strict": False,
        "spec_handoff": True,
    },
    "state": {
        "git_tracked": True,
    },
    # Plan-splitting thresholds (ADR-0003 §D2). Numeric budgets are tunable per
    # workspace; the structural rules (every plan is a directory, status in
    # frontmatter) are invariant and not configurable.
    "plans": {
        "step_file_threshold": 3,  # > N steps -> per-step files
        "readme_max_lines": 150,  # README split budget
        "step_max_lines": 80,  # step-file split budget
        "git_regime": "private",  # private | workspace (umbrella mode only)
    },
    # Risk-based strictness policy (RFC-0002 / ADR-0005). Control keys only; the
    # shipped taxonomy / tool->risk map / allowlist live as module constants below
    # (user-extensible via carter.yaml policy.tool_risk / policy.allowlist).
    # Default level is `loose` here so an existing config that omits `policy` keeps
    # today's behaviour (Q6); generate_default_config() bumps NEW installs to guarded.
    "policy": {
        "level": "loose",  # loose | guarded | strict
        "unknown_tool": "ask",  # gate for tools not in the risk map: allow | ask | deny
        "overrides": {},  # category -> gate, explicit per-category override
        "audit_overrides": True,  # log escape-hatch overrides via carter ops
    },
    "target": "copilot",
}


class ConfigError(Exception):
    """Raised when carter.yaml is invalid or missing required fields."""


def _validate_agent_suffix(suffix: Any) -> None:
    """Validate ``agent_suffix``: a lowercase alphanumeric/hyphen string or empty."""
    if not isinstance(suffix, str) or not _AGENT_SUFFIX_RE.match(suffix):
        raise ConfigError(
            f"Invalid agent_suffix: {suffix!r}. "
            "Must be a lowercase alphanumeric/hyphen string (or empty)."
        )


def load_config(config_path: Path) -> dict[str, Any]:
    """Load and validate carter.yaml from the given path.

    Merges with DEFAULT_CONFIG so partial configs get sensible defaults
    for optional sections. Lists use replace semantics (user's list wins).
    """
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ConfigError(f"Invalid config format in {config_path}")

    missing = REQUIRED_KEYS - config.keys()
    if missing:
        raise ConfigError(f"Missing required keys: {', '.join(sorted(missing))}")

    merged = _merge_with_defaults(config)
    _validate_agent_suffix(merged.get("agent_suffix", ""))
    return merged


def _merge_with_defaults(user_config: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge user config with DEFAULT_CONFIG.

    Rules:
    - Missing top-level keys get defaults
    - Missing nested dict keys get defaults (recursive for dicts)
    - Lists use replace semantics (user's list wins entirely)
    - Explicit None values are preserved
    - Extra user keys are preserved (forward-compatible)
    """
    defaults = copy.deepcopy(DEFAULT_CONFIG)
    return _deep_merge(defaults, user_config)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. Override wins for non-dict values."""
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Risk-based strictness policy model (RFC-0002 / ADR-0005)
# ──────────────────────────────────────────────────────────────────────────────
# The taxonomy, tool->risk map, and per-agent allowlist are shipped with Carter and
# user-extensible via carter.yaml. They are dict-shaped on purpose: `_deep_merge`
# replaces lists wholesale, so a list shape would let a single user override silently
# wipe the shipped defaults. Dicts merge key-by-key instead.

# Gate vocabulary, least -> most restrictive.
GATE_SEVERITY: dict[str, int] = {"allow": 0, "ask": 1, "gate": 2, "deny": 3}

# R0-R6 risk taxonomy: category -> {level -> gate}. Fixed, shipped with Carter.
RISK_TAXONOMY: dict[str, dict[str, str]] = {
    "R0": {"loose": "allow", "guarded": "allow", "strict": "allow"},  # read
    "R1": {"loose": "allow", "guarded": "allow", "strict": "allow"},  # local-write
    "R2": {"loose": "allow", "guarded": "ask", "strict": "gate"},  # remote-write
    "R3": {"loose": "allow", "guarded": "gate", "strict": "deny"},  # infra-mutate
    "R4": {"loose": "allow", "guarded": "ask", "strict": "gate"},  # secret-access
    "R5": {"loose": "allow", "guarded": "gate", "strict": "deny"},  # destructive
    "R6": {"loose": "allow", "guarded": "gate", "strict": "gate"},  # external-publish (overlay)
}

# Tool/command -> risk category. Shipped defaults; user-extensible via
# `policy.tool_risk` in carter.yaml (deep-merged over this map).
TOOL_RISK_MAP: dict[str, str] = {
    "git status": "R0", "git log": "R0", "git diff": "R0",
    "git add": "R1", "git commit": "R1",
    "git push": "R2", "git push --force": "R5",
    "terraform apply": "R3", "terraform destroy": "R3",
    "kubectl apply": "R3", "helm upgrade": "R3",
    "rm -rf": "R5", "git reset --hard": "R5",
    "vault read": "R4", "read .env": "R4",
}

# Per-agent allowlist: agent -> {category: True}. A category absent for an agent is
# denied for that agent (deny-by-default). dict-of-dicts so user tweaks deep-merge.
# Encodes the single-pusher invariant: devops is the sole R2 pusher, narrator the
# sole R6 author (narrator drafts/redacts, devops transmits via R2 on handoff).
AGENT_ALLOWLIST: dict[str, dict[str, bool]] = {
    "maestro": {"R0": True},
    "architect": {"R0": True},
    "engineer": {"R0": True, "R1": True},
    "devops": {"R0": True, "R1": True, "R2": True, "R3": True, "R4": True, "R5": True},
    "pm": {"R0": True, "R1": True},
    "learner": {"R0": True},
    "narrator": {"R0": True, "R1": True, "R6": True},
}


def most_restrictive_gate(gates: Iterable[str]) -> str:
    """Return the strictest gate among ``gates`` (allow < ask < gate < deny).

    Empty input resolves to ``allow`` (nothing to restrict).
    """
    strictest = "allow"
    for gate in gates:
        if GATE_SEVERITY[gate] > GATE_SEVERITY[strictest]:
            strictest = gate
    return strictest


def resolve_action_gate(
    categories: Iterable[str],
    level: str,
    taxonomy: dict[str, dict[str, str]] | None = None,
) -> str:
    """Resolve the effective gate for an action at ``level``.

    An action may match multiple risk categories (e.g. ``git push --force`` is both
    R2 remote-write and R5 destructive); most-restrictive-wins.
    """
    tax = taxonomy if taxonomy is not None else RISK_TAXONOMY
    return most_restrictive_gate(tax[category][level] for category in categories)


def effective_tool_risk_map(config: dict[str, Any]) -> dict[str, str]:
    """Shipped tool->risk map with any ``policy.tool_risk`` overrides merged on top."""
    overrides = (config.get("policy") or {}).get("tool_risk", {})
    return _deep_merge(copy.deepcopy(TOOL_RISK_MAP), overrides)


def effective_allowlist(config: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Shipped per-agent allowlist with any ``policy.allowlist`` overrides merged on top."""
    overrides = (config.get("policy") or {}).get("allowlist", {})
    return _deep_merge(copy.deepcopy(AGENT_ALLOWLIST), overrides)


def generate_default_config(
    workspace_name: str = "my-workspace",
    mode: str = "umbrella",
) -> dict[str, Any]:
    """Generate a default config dict for a new workspace."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["workspace"] = {
        "name": workspace_name,
        "description": "",
        "mode": mode,
    }
    # Q6: new installs default to `guarded`; an existing config that omits the
    # policy block keeps `loose` (the DEFAULT_CONFIG value) for no behaviour change.
    config["policy"]["level"] = "guarded"
    return config


def write_config(config_path: Path, config: dict[str, Any]) -> None:
    """Write config dict to a YAML file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
