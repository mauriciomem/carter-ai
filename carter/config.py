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
    # Risk-based strictness policy (RFC-0002 / ADR-0005; refreshed by ADR-0010).
    # Control keys only; the shipped taxonomy / tool->risk map / allowlist live as
    # module constants below (user-extensible via carter.yaml policy.tool_risk /
    # policy.allowlist). `guarded` is the floor and the default for everything (new
    # and existing/omitted) — ADR-0010 D3 reduced strictness to two levels, so an
    # absent or unrecognized level resolves to `guarded` through this default.
    "policy": {
        "level": "guarded",  # guarded | strict
        "unknown_tool": "ask",  # gate for tools not in the risk map: allow | ask | deny
        "overrides": {},  # category -> gate, explicit per-category override
        "audit_overrides": True,  # log escape-hatch overrides via carter ops
    },
    # Per-agent model (ADR-0010 D2). Dict-shaped per tier (so `_deep_merge` doesn't
    # wipe it — same footgun the taxonomy maps avoid). Each tier maps a target to a
    # single model string: a display name for VS Code/Copilot, a `provider/model` ID
    # for OpenCode. Resolved `overrides > tier > default` (see `resolve_model`).
    # Thinkers = Opus 4.8; implementers = Sonnet 4.6; Haiku is opt-in via `overrides`.
    # Effort is NOT here — no target has a per-agent effort field; it is the global
    # `--effort high` knob (D2.D1). `temperature` is dropped wholesale (D7).
    "models": {
        "default": {"copilot": "Claude Opus 4.8", "opencode": "anthropic/claude-opus-4-8"},
        "thinkers": {"copilot": "Claude Opus 4.8", "opencode": "anthropic/claude-opus-4-8"},
        "implementers": {
            "copilot": "Claude Sonnet 4.6",
            "opencode": "anthropic/claude-sonnet-4-6",
        },
        "overrides": {},  # per-agent, e.g. {engineer: {copilot: "Claude Haiku 4.5", ...}}
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


def _validate_policy(policy: Any) -> None:
    """Validate the ``policy`` block at the config boundary.

    Normalizes an out-of-vocabulary ``policy.level`` to the ``guarded`` default
    (ADR-0010 D3) and catches an override category/gate that isn't a known keyword,
    so a typo there fails fast with a clear ``ConfigError`` instead of a raw
    ``KeyError`` deep in rendering. ``GATE_SEVERITY``/``POLICY_LEVELS`` are defined
    below in the policy-model section.
    """
    if not isinstance(policy, dict):
        raise ConfigError(f"Invalid policy block: {policy!r} (must be a mapping)")
    level = policy.get("level", "guarded")
    # ADR-0010 D3: strictness is now `guarded`/`strict` only. Any level outside that
    # set — a stale value from a prior install, or anything unrecognized — normalizes
    # to the `guarded` default in-place, silently (no notice, no dedicated migration
    # branch) so it resolves via the normal default path everywhere downstream.
    if level not in POLICY_LEVELS:
        policy["level"] = level = "guarded"
    for cat, gate in (policy.get("overrides") or {}).items():
        if cat not in RISK_TAXONOMY:
            raise ConfigError(
                f"Invalid policy.overrides category {cat!r}. "
                f"Must be one of: {', '.join(RISK_TAXONOMY)}."
            )
        if gate not in GATE_SEVERITY:
            raise ConfigError(
                f"Invalid policy.overrides[{cat!r}]: {gate!r}. "
                f"Must be one of: {', '.join(GATE_SEVERITY)}."
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
    _validate_policy(merged.get("policy", {}))
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
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
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

# Valid strictness levels (validated at the config boundary). ADR-0010 D3 reduced
# these to two; `guarded` is the floor and default.
POLICY_LEVELS: tuple[str, ...] = ("guarded", "strict")

# 4-category risk taxonomy (ADR-0010 D4): category -> {level -> gate}. Fixed,
# shipped with Carter. Collapsed from the old seven: reading secrets gates the same
# as any remote/infra path so it folds into `remote-write`; infra-mutation and
# destructive actions fold into `dangerous`; and the old external-publish overlay is
# dropped — redaction is now an enforced `gate`-tier narrator handoff in the
# allowlist (D5), not a taxonomy category.
RISK_TAXONOMY: dict[str, dict[str, str]] = {
    "read": {"guarded": "allow", "strict": "allow"},
    "local-write": {"guarded": "allow", "strict": "allow"},
    "remote-write": {"guarded": "ask", "strict": "gate"},  # incl. reading secrets
    "dangerous": {"guarded": "gate", "strict": "deny"},  # infra-mutate + destructive
}

# Tool/command -> risk category. Shipped defaults; user-extensible via
# `policy.tool_risk` in carter.yaml (deep-merged over this map). Secret reads
# (`vault read`, `read .env`) classify as `remote-write` (they gate identically).
TOOL_RISK_MAP: dict[str, str] = {
    "git status": "read",
    "git log": "read",
    "git diff": "read",
    "git add": "local-write",
    "git commit": "local-write",
    "git push": "remote-write",
    "git push --force": "dangerous",
    "terraform apply": "dangerous",
    "terraform destroy": "dangerous",
    "kubectl apply": "dangerous",
    "helm upgrade": "dangerous",
    "rm -rf": "dangerous",
    "git reset --hard": "dangerous",
    "vault read": "remote-write",
    "read .env": "remote-write",
}

# Per-agent allowlist (ADR-0010 D4): agent -> {category: True}. A category absent
# for an agent is denied for that agent (deny-by-default). dict-of-dicts so user
# tweaks deep-merge. Encodes the single-pusher invariant structurally: devops is the
# sole holder of `remote-write` and `dangerous`. The narrator is first-class —
# {read, local-write} like pm/engineer — and reaches `remote-write` only via the
# `gate`-tier redaction handoff to devops (D5), never by holding the category.
AGENT_ALLOWLIST: dict[str, dict[str, bool]] = {
    "maestro": {"read": True},
    "architect": {"read": True},
    "learner": {"read": True},
    "pm": {"read": True, "local-write": True},
    "narrator": {"read": True, "local-write": True},
    "engineer": {"read": True, "local-write": True},
    "devops": {
        "read": True,
        "local-write": True,
        "remote-write": True,
        "dangerous": True,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Per-agent model (ADR-0010 D2 / RFC-0005 §2)
# ──────────────────────────────────────────────────────────────────────────────
# MODEL LAUNCH — KEEP IN SYNC. The Carter→target model-name table: one home for the
# canonical Anthropic model id ⇄ the per-target string Carter emits (display name for
# VS Code/Copilot, `provider/model` id for OpenCode). When a model is bumped, update
# this table AND the `models:` tiers in DEFAULT_CONFIG above. Model ids verified
# against the bundled `claude-api` skill (cached 2026-06-04): a stale string here is a
# silently dead agent (test_models.py asserts the table is non-empty per shipped role).
MODEL_NAMES: dict[str, dict[str, str]] = {
    "claude-opus-4-8": {"copilot": "Claude Opus 4.8", "opencode": "anthropic/claude-opus-4-8"},
    "claude-sonnet-4-6": {
        "copilot": "Claude Sonnet 4.6",
        "opencode": "anthropic/claude-sonnet-4-6",
    },
    # Haiku 4.5 is an opt-in implementer override only (xhigh/max effort error on it).
    "claude-haiku-4-5": {"copilot": "Claude Haiku 4.5", "opencode": "anthropic/claude-haiku-4-5"},
}

# Role → model tier (ADR-0010 D2). Thinkers run the documentation-authoring agents on
# the high-reasoning model; implementers run the cheaper one. A role in no tier
# resolves to `models.default` (the un-tiered catch-all) so it never resolves empty.
MODEL_TIERS: dict[str, str] = {
    "maestro": "thinkers",
    "architect": "thinkers",
    "pm": "thinkers",
    "learner": "thinkers",
    "narrator": "thinkers",
    "engineer": "implementers",
    "devops": "implementers",
}


def resolve_model(config: dict[str, Any], role: str) -> str:
    """The per-target ``model:`` string for ``role``, resolved ``overrides > tier > default``.

    (1) ``models.overrides[role]`` if present; else (2) the role's tier
    (``thinkers``/``implementers``); else (3) ``models.default`` (the un-tiered
    catch-all). The value is a SINGLE string — a display name for VS Code/Copilot, a
    ``provider/model`` id for OpenCode (never an array, which breaks Copilot CLI).
    """
    models = config.get("models") or DEFAULT_CONFIG["models"]
    target = config.get("target", "copilot")
    # OpenCode shares the `opencode` key; `all` and any other target map to copilot's
    # display name (the default emission surface).
    key = "opencode" if target == "opencode" else "copilot"

    override = (models.get("overrides") or {}).get(role)
    if override and override.get(key):
        return override[key]
    tier = MODEL_TIERS.get(role)
    if tier and (models.get(tier) or {}).get(key):
        return models[tier][key]
    return (models.get("default") or {}).get(key, "")


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
    ``remote-write`` and ``dangerous``); most-restrictive-wins.
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


# ──────────────────────────────────────────────────────────────────────────────
# Per-target frontmatter emission (RFC-0002 / ADR-0005, P2)
# ──────────────────────────────────────────────────────────────────────────────
# Carter is a scaffolder, not a runtime: it emits the per-agent allowlist + gates
# into agent frontmatter using the most authoritative native primitive per target,
# with a deterministic, target-agnostic `policy:` block as the source of truth the
# P3 lint validates. Per-agent MCP scope lives here (agent frontmatter), never in
# the global `configure_mcp_servers` wiring.

# Per-agent MCP server scope, mirroring each static agent's <mcp> block. Drives the
# copilot/VS Code `tools:` allowlist. An agent that wires no MCP servers (the
# maestro orchestrator; the narrator, which authors content via skills rather than
# calling a remote MCP) emits no `tools:` key — a domain fact, not a special case.
AGENT_MCP_SCOPE: dict[str, list[str]] = {
    "maestro": [],
    "architect": ["github", "terraform"],
    "engineer": ["github", "terraform"],
    "devops": ["github", "terraform"],
    "pm": ["atlassian", "github"],
    "learner": ["atlassian"],
    "narrator": [],
}

# OpenCode's permission model has no `gate` tier, so Carter's `gate` degrades to
# `ask` (the closest "prompt the human" semantics); `allow`/`deny` pass through.
_OPENCODE_GATE: dict[str, str] = {
    "allow": "allow",
    "ask": "ask",
    "gate": "ask",
    "deny": "deny",
}

# Representative shell commands per shell-risk category, used to gate/deny the
# OpenCode `bash` path with command globs so it can't bypass the allowlist.
_BASH_COMMANDS: dict[str, tuple[str, ...]] = {
    "remote-write": ("git push*",),
    "dangerous": (
        "terraform apply*",
        "terraform destroy*",
        "kubectl apply*",
        "helm upgrade*",
        "rm -rf*",
        "git reset --hard*",
        "git push --force*",
    ),
}

# Human-readable label per risk category, for the maestro policy gate table. With
# the 4-category taxonomy (ADR-0010 D4) the id IS the label.
RISK_LABELS: dict[str, str] = {
    "read": "read",
    "local-write": "local-write",
    "remote-write": "remote-write",
    "dangerous": "dangerous",
}


def _emit_level(level: str) -> str:
    """The strictness level Carter emits.

    ``strict`` emits its real gate map (``dangerous`` ``deny``), backed by the
    `carter check` lint (hard ack on a non-enforcing target) and the single-action
    override ledger. This is the identity today; it remains a single seam so a
    future level remap has one home.
    """
    return level


def _opencode_permission(allowed: list[str], gates: dict[str, str]) -> dict[str, Any]:
    """Best-effort OpenCode ``permission`` map from an agent's allowlist x gates.

    ``edit`` follows ``local-write``. ``bash`` is a command-glob map: local shell
    stays available (a ``local-write`` agent needs ``pytest``/local ``git``; a
    read-only agent gets ``ask``), while commands in a shell-risk category the agent
    does NOT hold are denied — so the bash path can't bypass the declared allowlist.
    ``webfetch`` is always allowed. Carter ``gate`` degrades to ``ask`` (OpenCode has
    no gate).
    """
    edit = "allow" if "local-write" in allowed else "deny"
    return {
        "edit": edit,
        "bash": _opencode_bash(allowed, gates),
        "webfetch": "allow",
    }


def _opencode_bash(allowed: list[str], gates: dict[str, str]) -> dict[str, str]:
    """OpenCode ``bash`` permission as ``{command-glob: action}`` rules.

    The ``*`` baseline (first, lowest precedence — OpenCode applies the last
    matching rule) allows local shell for a local-write agent, or ``ask`` for a
    read-only one. Each shell-risk command then resolves to its category's gate if
    the agent holds it, or ``deny`` if not.
    """
    baseline = "allow" if "local-write" in allowed else "ask"
    rules: dict[str, str] = {"*": baseline}
    for cat, commands in _BASH_COMMANDS.items():
        verdict = _OPENCODE_GATE[gates[cat]] if cat in allowed else "deny"
        for cmd in commands:
            rules[cmd] = verdict
    return rules


def _gates_for(
    allowed: list[str], emit_level: str, overrides: dict[str, str] | None = None
) -> dict[str, str]:
    """The gate per allowed category at ``emit_level``, with ``policy.overrides``
    applied on top (an explicit per-category override replaces the level gate).
    """
    overrides = overrides or {}
    return {cat: overrides.get(cat, RISK_TAXONOMY[cat][emit_level]) for cat in allowed}


# The primary orchestrator (the only router) and the subagent dispatch primitive.
# Native subagent dispatch (ADR-0010 D1) is emitted ONLY on the primary, as an
# EXPLICIT per-specialist allowlist — never `'*'` and never a `carter-*` glob (D1.2,
# a security boundary: a glob auto-trusts any future `carter-*` agent; `'*'` lets the
# maestro delegate to any workspace agent, failure-open). The chain is flat — every
# specialist carries `agents: []` (D1.3) so the maestro is the only router.
PRIMARY_ROLE = "maestro"


def _suffixed_agent(role: str, config: dict[str, Any]) -> str:
    """``carter-<role>`` honoring ``agent_suffix`` (e.g. ``carter-engineer-local``).

    The dispatch allowlist must reference the same suffixed files the rest of the
    rendered agent body does, and the lint recomputes against already-suffixed
    installed frontmatter — so emission carries the suffix here rather than relying
    on the post-render rewrite (which is idempotent over these names anyway).
    """
    raw = (config.get("agent_suffix") or "").strip()
    return f"carter-{role}{('-' + raw) if raw else ''}"


def dispatch_specialists(config: dict[str, Any]) -> list[str]:
    """The explicit per-specialist dispatch allowlist for the primary (sorted).

    Every configured agent except the primary, as suffixed ``carter-<role>`` names.
    This is the security boundary the fail-closed lint validates (D1.2).
    """
    return sorted(
        _suffixed_agent(role, config) for role in config.get("agents", []) if role != PRIMARY_ROLE
    )


def policy_native_keys(config: dict[str, Any], role: str) -> dict[str, Any]:
    """The target-native enforcement keys Carter emits for ``role``.

    ``tools`` (copilot/all): the per-agent MCP server scope, when any; the primary
    additionally carries the ``agent`` subagent tool. ``agents``/``handoffs``
    (copilot/all): native subagent dispatch — an EXPLICIT per-specialist allowlist on
    the primary, ``[]`` on every specialist (flat chain, D1.3). ``permission``
    (opencode/all): the best-effort native gate map; the primary's also carries a
    ``task`` allowlist (``'*': deny`` + explicit per-specialist ``allow``). Pure
    function of the model + target — the single source both ``policy_frontmatter``
    (emission) and ``lint_policy`` (drift detection) derive these enforced keys from.
    """
    target = config.get("target", "copilot")
    policy = config.get("policy") or {}
    emit_level = _emit_level(policy.get("level", "guarded"))
    allowed = [cat for cat, on in sorted(effective_allowlist(config).get(role, {}).items()) if on]
    gates = _gates_for(allowed, emit_level, policy.get("overrides"))
    is_primary = role == PRIMARY_ROLE
    specialists = dispatch_specialists(config)

    keys: dict[str, Any] = {}
    # Per-agent model (D2): a SINGLE per-target string on every agent, resolved
    # overrides > tier > default. Emitted for all targets (the value's shape is
    # target-specific). `carter check` prints the unverifiable-model advisory.
    model = resolve_model(config, role)
    if model:
        keys["model"] = model
    if target in ("copilot", "all"):
        scope = [f"carter-{server}/*" for server in sorted(AGENT_MCP_SCOPE.get(role, []))]
        # The primary enables the `agent` subagent tool (first, ahead of any MCP
        # scope); specialists only ever carry their MCP scope.
        tools = (["agent"] + scope) if is_primary else scope
        if tools:
            keys["tools"] = tools
        # Native dispatch allowlist (VS Code/Copilot): explicit on the primary, empty
        # on every specialist (flat one-level chain). `handoffs:` is the user-approved
        # confirm surface for the same delegation set (D1.1).
        if is_primary:
            # Independent list copies so YAML emits each inline (no &anchor/*alias
            # that a downstream parser/editor might choke on).
            keys["agents"] = list(specialists)
            keys["handoffs"] = list(specialists)
        else:
            keys["agents"] = []
    if target in ("opencode", "all"):
        permission = _opencode_permission(allowed, gates)
        if is_primary:
            # OpenCode `permission.task`: fail-closed `'*': deny` + an explicit allow
            # per specialist (never a `carter-*` glob — D1.2).
            permission["task"] = {"*": "deny", **dict.fromkeys(specialists, "allow")}
        keys["permission"] = permission
    return keys


def policy_frontmatter(config: dict[str, Any], role: str) -> str:
    """Render the per-agent strictness-policy frontmatter for ``role``.

    Returns YAML lines (no surrounding ``---``, no trailing newline) carrying:

    - ``policy``: the deterministic, target-agnostic source of truth — the agent's
      allowed risk categories and the active level's gate per allowed category.
      Always emitted; this is what the P3 lint validates.
    - ``tools`` (copilot/all targets): the per-agent MCP server scope, when any.
    - ``permission`` (opencode/all targets): the best-effort native map.

    The P2->P3 gate is open (step 9): ``strict`` emits its real gate map, gated
    operationally by the `carter check` hard ack on a non-enforcing target.
    """
    policy = config.get("policy") or {}
    level = policy.get("level", "guarded")
    emit_level = _emit_level(level)

    allowed = [cat for cat, on in sorted(effective_allowlist(config).get(role, {}).items()) if on]
    gates = _gates_for(allowed, emit_level, policy.get("overrides"))

    block: dict[str, Any] = {
        "policy": {"level": emit_level, "allow": allowed, "gates": gates},
    }
    block.update(policy_native_keys(config, role))

    text = yaml.dump(block, sort_keys=False, default_flow_style=None).rstrip("\n")
    return text


def policy_gate_table(config: dict[str, Any]) -> list[dict[str, str]]:
    """Rows for the maestro's always-on risk/gate table at the active level.

    One row per category (the 4-category taxonomy, ADR-0010 D4): ``category`` id,
    human ``label``, and the active level's ``gate`` with any ``policy.overrides``
    applied. ``strict`` shows the real ``deny`` row for ``dangerous``.
    """
    policy = config.get("policy") or {}
    level = _emit_level(policy.get("level", "guarded"))
    overrides = policy.get("overrides") or {}
    cats = ("read", "local-write", "remote-write", "dangerous")
    gates = _gates_for(list(cats), level, overrides)
    return [{"category": cat, "label": RISK_LABELS[cat], "gate": gates[cat]} for cat in cats]


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
    # ADR-0010 D3: `guarded` is the floor and the DEFAULT_CONFIG value, so new
    # installs and existing/omitted configs both resolve to it — no per-install bump.
    return config


def write_config(config_path: Path, config: dict[str, Any]) -> None:
    """Write config dict to a YAML file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
