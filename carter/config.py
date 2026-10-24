"""Configuration loading and schema validation for carter.yaml."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

REQUIRED_KEYS = {"version", "workspace", "identity", "agents"}

# agent_suffix becomes part of scaffolded agent filenames/names
# (e.g. carter-engineer-local). Lowercase alphanumeric + hyphen, or empty.
_AGENT_SUFFIX_RE = re.compile(r"^[a-z0-9-]*$")

# docs_language: a simple BCP 47-style language tag (en, es, pt-BR, zh-Hant).
_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

DEFAULT_CONFIG: dict[str, Any] = {
    "version": "2",
    "workspace": {
        "name": "my-workspace",
        "mode": "umbrella",
    },
    "identity": {
        "git_account": "",
        "bot_name": "carter-bot",
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
        "security",
    ],
    # Suffix distinguishing workspace-scaffolded agents from globally installed
    # ones (e.g. carter-engineer-local). Empty string = same names as global.
    "agent_suffix": "local",
    "quality_gate": {
        "enabled": True,
        "max_iterations": 2,
    },
    "redaction": {
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
    # Plan-splitting thresholds. Numeric budgets are tunable per
    # workspace; the structural rules (every plan is a directory, status in
    # frontmatter) are invariant and not configurable.
    "plans": {
        "step_file_threshold": 3,  # > N steps -> per-step files
        "readme_max_lines": 150,  # README split budget
        "step_max_lines": 80,  # step-file split budget
    },
    # Risk-based strictness policy. Control keys only; the shipped taxonomy and
    # per-agent allowlist live as module constants below (the allowlist is
    # user-extensible via carter.yaml policy.allowlist). `guarded` is the floor
    # and the default for everything (new and existing/omitted) — strictness is two
    # levels only, so an absent or unrecognized level resolves to `guarded` through
    # this default.
    "policy": {
        "level": "guarded",  # guarded | strict
        "overrides": {},  # category -> gate, explicit per-category override
    },
    # Per-agent model (ADR-0014 D4). Each tier is ONE OpenCode V2 model string,
    # `provider/model[#variant]`. Resolved `overrides > profile > tier > default`
    # (see `resolve_model`). Thinkers = Opus 5.5; implementers = Sonnet 5.5; Haiku 5.5
    # is opt-in via `overrides`. No per-agent effort; `temperature` is never emitted.
    "models": {
        "default": "anthropic/claude-opus-5-5",
        "thinkers": "anthropic/claude-opus-5-5",
        "implementers": "anthropic/claude-sonnet-5-5",
        "overrides": {},  # per-agent, e.g. {engineer: "anthropic/claude-haiku-5-5"}
    },
    # Language for Carter's internal documentation only: ADRs, RFCs, and everything
    # under .carter/ (plans, knowledge, checkpoints) plus memories. Repository output
    # (commits, code comments, docs, PRs, issues, Jira, Slack) is always English.
    "docs_language": "en",
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


def _validate_docs_language(tag: Any) -> None:
    """Validate ``docs_language``: a simple language tag such as ``en`` or ``pt-BR``."""
    if not isinstance(tag, str) or not _LANGUAGE_TAG_RE.match(tag):
        raise ConfigError(
            f"Invalid docs_language: {tag!r}. Must be a language tag such as 'en', 'es' or 'pt-BR'."
        )


def _validate_profile(profile: Any) -> None:
    """Validate the optional ``profile`` key: unset/None, or a known profile name.

    Rejects a typo loudly at the config boundary (a clear ``ConfigError`` instead of a
    silently-ignored profile that leaves everyone on the default tiers). ``PROFILES`` is
    defined below in the per-agent-model section.
    """
    if profile is None:
        return
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ConfigError(
            f"Invalid profile: {profile!r}. Must be one of: {', '.join(sorted(PROFILES))} "
            "(or omit the key)."
        )


# OpenCode V2 model reference: `provider/model` with an optional `#variant`. The
# model part may itself contain `/` (e.g. `openrouter/meta/llama-4`).
_MODEL_RE = re.compile(r"^[^\s/#]+/[^\s#]+(#[^\s#]+)?$")


def _validate_no_target(user_config: dict[str, Any], config_path: Path) -> None:
    """Reject a leftover ``target:`` key (ADR-0014 D4: removed, no shim)."""
    if "target" in user_config:
        raise ConfigError(
            f"Unknown key 'target' in {config_path}. Delete the `target:` key: "
            "Carter now only supports OpenCode >= 2.1, so there is no target to choose."
        )


def _validate_models(models: Any) -> None:
    """Validate the ``models`` block: every tier/override is a V2 model string."""
    if not isinstance(models, dict):
        raise ConfigError(f"Invalid models block: {models!r} (must be a mapping)")
    hint = "Must be a single 'provider/model[#variant]' string, e.g. 'anthropic/claude-opus-5-5'."
    entries = [(f"models.{k}", v) for k, v in models.items() if k != "overrides"]
    overrides = models.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ConfigError(f"Invalid models.overrides: {overrides!r} (must be a mapping)")
    entries += [(f"models.overrides.{role}", v) for role, v in overrides.items()]
    for where, value in entries:
        if not isinstance(value, str) or not _MODEL_RE.match(value):
            raise ConfigError(f"Invalid {where}: {value!r}. {hint}")


def _validate_policy(policy: Any) -> None:
    """Validate the ``policy`` block at the config boundary.

    Normalizes an out-of-vocabulary ``policy.level`` to the ``guarded`` default
    and catches an override category/gate that isn't a known keyword,
    so a typo there fails fast with a clear ``ConfigError`` instead of a raw
    ``KeyError`` deep in rendering. ``GATE_SEVERITY``/``POLICY_LEVELS`` are defined
    below in the policy-model section.
    """
    if not isinstance(policy, dict):
        raise ConfigError(f"Invalid policy block: {policy!r} (must be a mapping)")
    level = policy.get("level", "guarded")
    # Strictness is `guarded`/`strict` only. Any level outside that
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

    _validate_no_target(config, config_path)
    merged = _merge_with_defaults(config)
    _validate_models(merged.get("models"))
    _validate_agent_suffix(merged.get("agent_suffix", ""))
    _validate_policy(merged.get("policy", {}))
    _validate_profile(merged.get("profile"))
    _validate_docs_language(merged.get("docs_language"))
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
# Risk-based strictness policy model
# ──────────────────────────────────────────────────────────────────────────────
# The taxonomy and per-agent allowlist are shipped with Carter; the allowlist is
# user-extensible via carter.yaml. They are dict-shaped on purpose: `_deep_merge`
# replaces lists wholesale, so a list shape would let a single user override silently
# wipe the shipped defaults. Dicts merge key-by-key instead.

# Gate vocabulary, least -> most restrictive.
GATE_SEVERITY: dict[str, int] = {"allow": 0, "ask": 1, "gate": 2, "deny": 3}

# Valid strictness levels (validated at the config boundary). There are two;
# `guarded` is the floor and default.
POLICY_LEVELS: tuple[str, ...] = ("guarded", "strict")

# 4-category risk taxonomy: category -> {level -> gate}. Fixed, shipped with
# Carter. Collapsed from an earlier seven: reading secrets gates the same as any
# remote/infra path so it folds into `remote-write`; infra-mutation and destructive
# actions fold into `dangerous`; and the old external-publish overlay is dropped —
# redaction is an enforced `gate`-tier narrator handoff in the allowlist, not a
# taxonomy category.
RISK_TAXONOMY: dict[str, dict[str, str]] = {
    "read": {"guarded": "allow", "strict": "allow"},
    "local-write": {"guarded": "allow", "strict": "allow"},
    "remote-write": {"guarded": "ask", "strict": "gate"},  # incl. reading secrets
    "dangerous": {"guarded": "gate", "strict": "deny"},  # infra-mutate + destructive
}

# Per-agent allowlist: agent -> {category: True}. A category absent
# for an agent is denied for that agent (deny-by-default). dict-of-dicts so user
# tweaks deep-merge. Encodes the single-pusher invariant structurally: devops is the
# sole holder of `remote-write` and `dangerous`. The narrator is first-class —
# {read, local-write} like pm/engineer — and reaches `remote-write` only via the
# `gate`-tier redaction handoff to devops, never by holding the category.
AGENT_ALLOWLIST: dict[str, dict[str, bool]] = {
    "maestro": {"read": True},
    "architect": {"read": True},
    "learner": {"read": True},
    "pm": {"read": True, "local-write": True},
    "narrator": {"read": True, "local-write": True},
    "engineer": {"read": True, "local-write": True},
    "security": {"read": True, "local-write": True},
    "devops": {
        "read": True,
        "local-write": True,
        "remote-write": True,
        "dangerous": True,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Per-agent model
# ──────────────────────────────────────────────────────────────────────────────
# Role → model tier. Thinkers run on the high-reasoning model; implementers run the
# cheaper one. A role in no tier resolves to `models.default` (the un-tiered catch-all)
# so it never resolves empty.
#
# narrator + pm are `implementers` (Sonnet) by DEFAULT:
# their work is structured — narrator's redaction is rule-bound, pm's planning follows
# carter-plan's schema — and both cleared the adherence gate on Sonnet 4.6 (>=0.90, 0
# critical). `profile: quality` restores them (and everyone) to Opus; `profile: budget`
# additionally moves learner. maestro/architect/learner/security stay `thinkers`
# (routing quality-gates everything; deep reasoning).
MODEL_TIERS: dict[str, str] = {
    "maestro": "thinkers",
    "architect": "thinkers",
    "learner": "thinkers",
    "security": "thinkers",
    "pm": "implementers",
    "narrator": "implementers",
    "engineer": "implementers",
    "devops": "implementers",
}


# Cost profiles (resolved lazily at render, NOT
# written as concrete overrides). A `profile:` key in carter.yaml re-tiers roles at
# resolution time, layered BETWEEN explicit per-agent overrides and the base tier:
# `models.overrides > profile > tier > default`. The value maps role → tier name, so a
# profile reuses the same `models:` tier model strings (no per-profile model literals to
# keep in sync). An absent/unset profile uses the shipped default tiers (MODEL_TIERS).
#
#   quality — every agent on the `thinkers` (Opus) tier: restores the earlier
#             default for users who prefer max quality over cost.
#   budget  — the cheaper default PLUS learner → implementers (Sonnet); the furthest
#             push that still cleared review. (narrator/pm are already implementers by
#             default, so budget's marginal move is learner.)
PROFILES: dict[str, dict[str, str]] = {
    "quality": dict.fromkeys(MODEL_TIERS, "thinkers"),
    "budget": {**MODEL_TIERS, "learner": "implementers"},
}


def _profile_tier(config: dict[str, Any], role: str) -> str | None:
    """The tier ``role`` maps to under the active ``profile:``, or ``None`` if no profile.

    An unset/absent profile returns ``None`` (fall through to the base ``MODEL_TIERS``).
    An unknown profile value is treated as unset here — the config boundary
    (``_validate_profile``) is what rejects it loudly; resolution stays fail-soft.
    """
    profile = config.get("profile")
    if not profile:
        return None
    return PROFILES.get(profile, {}).get(role)


def resolve_model(config: dict[str, Any], role: str) -> str:
    """The ``model:`` string (``provider/model[#variant]``) for ``role``.

    Resolution order: ``models.overrides[role]`` > active ``profile:`` tier > the role's
    base tier (``MODEL_TIERS``) > ``models.default`` (the un-tiered catch-all).
    """
    models = config.get("models") or DEFAULT_CONFIG["models"]
    override = (models.get("overrides") or {}).get(role)
    if override:
        return str(override)
    # A `profile:` re-tiers the role; it wins over the base tier but not an explicit
    # per-agent override above.
    tier = _profile_tier(config, role) or MODEL_TIERS.get(role)
    if tier and models.get(tier):
        return str(models[tier])
    return str(models.get("default") or "")


def effective_allowlist(config: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Shipped per-agent allowlist with any ``policy.allowlist`` overrides merged on top."""
    overrides = (config.get("policy") or {}).get("allowlist", {})
    return _deep_merge(copy.deepcopy(AGENT_ALLOWLIST), overrides)


# ──────────────────────────────────────────────────────────────────────────────
# Agent frontmatter emission (OpenCode V2 `permissions:`, ADR-0014 D1)
# ──────────────────────────────────────────────────────────────────────────────
# Carter is a scaffolder, not a runtime: it emits each agent's allowlist x gates as
# an ordered V2 `permissions:` rule list (last match wins). That list is the single
# enforceable truth; `carter check` compares it with what carter.yaml generates.

# V1 agent frontmatter keys. A file carrying V2 `permissions` is read as V2 and these
# are ignored with a warning (https://opencode.ai/v2/docs/migrate-v1/), so Carter
# never emits them and the lint rejects them.
V1_AGENT_KEYS: tuple[str, ...] = ("permission", "tools", "bash", "task", "name", "temperature")

# V2 effects are allow/deny/ask only, so Carter `gate` is emitted as `ask` (D2).
_OPENCODE_GATE: dict[str, str] = {
    "allow": "allow",
    "ask": "ask",
    "gate": "ask",
    "deny": "deny",
}

# Representative shell commands per shell-risk category. V2 glob form: a pattern
# ending in ` *` also matches the bare command (`git push *` matches `git push`).
_BASH_COMMANDS: dict[str, tuple[str, ...]] = {
    "remote-write": ("git push *",),
    "dangerous": (
        "terraform apply *",
        "terraform destroy *",
        "kubectl apply *",
        "helm upgrade *",
        "rm -rf *",
        "git reset --hard *",
        "git push --force *",
    ),
}

# Actions every agent may use without prompting (D1 step 2).
_DISCOVERY_ACTIONS: tuple[str, ...] = ("read", "glob", "grep", "skill", "question")

# The primary orchestrator — the only agent allowed to launch subagents (flat chain).
PRIMARY_ROLE = "maestro"

Rule = dict[str, str]


def _rule(action: str, resource: str, effect: str) -> Rule:
    return {"action": action, "resource": resource, "effect": effect}


def _gates_for(
    allowed: list[str], level: str, overrides: dict[str, str] | None = None
) -> dict[str, str]:
    """The gate per allowed category at ``level``, with ``policy.overrides``
    applied on top (an explicit per-category override replaces the level gate).
    """
    overrides = overrides or {}
    return {cat: overrides.get(cat, RISK_TAXONOMY[cat][level]) for cat in allowed}


def permission_rules(config: dict[str, Any], role: str) -> list[Rule]:
    """The ordered V2 ``permissions:`` rules for ``role`` (ADR-0014 D1; last match wins).

    1. ``* *`` ask baseline (overrides V2's ``*:*:allow`` base).
    2. Discovery actions allowed.
    3. The base ``.env`` read rules re-appended (step 2 would shadow them).
    4. Carter state under ``~/.carter``: readable by all, memories editable by
       ``local-write`` holders.
    5. ``subagent * → deny``; the maestro alone then allows ``carter-*``.
    6. Category rules from the allowlist x gates; ``gate`` emitted as ``ask``.
    Anything else (MCP tools, websearch, execute) falls to the baseline ask.
    """
    policy = config.get("policy") or {}
    level = policy.get("level", "guarded")
    allowed = [cat for cat, on in sorted(effective_allowlist(config).get(role, {}).items()) if on]
    gates = _gates_for(allowed, level, policy.get("overrides"))
    writes = "local-write" in allowed

    rules = [_rule("*", "*", "ask")]
    rules += [_rule(action, "*", "allow") for action in _DISCOVERY_ACTIONS]
    rules += [
        _rule("read", "*.env", "ask"),
        _rule("read", "*.env.*", "ask"),
        _rule("read", "*.env.example", "allow"),
    ]
    rules += [
        _rule("external_directory", "~/.carter/*", "allow"),
        _rule("read", "~/.carter/*", "allow"),
    ]
    if writes:
        rules.append(_rule("edit", "~/.carter/memories/*", "allow"))
    rules.append(_rule("subagent", "*", "deny"))
    if role == PRIMARY_ROLE:
        rules.append(_rule("subagent", "carter-*", "allow"))
    local = "allow" if writes else "ask"
    rules += [_rule(action, "*", local) for action in ("edit", "shell", "webfetch")]
    for cat, commands in _BASH_COMMANDS.items():
        effect = _OPENCODE_GATE[gates[cat]] if cat in allowed else "deny"
        rules += [_rule("shell", cmd, effect) for cmd in commands]
    return rules


def policy_native_keys(config: dict[str, Any], role: str) -> dict[str, Any]:
    """The enforced frontmatter keys Carter emits for ``role``: ``model`` + ``permissions``.

    Pure function of carter.yaml — the single source both emission
    (:func:`policy_frontmatter`) and the lint derive these keys from.
    """
    keys: dict[str, Any] = {}
    model = resolve_model(config, role)
    if model:
        keys["model"] = model
    keys["permissions"] = permission_rules(config, role)
    return keys


def policy_frontmatter(config: dict[str, Any], role: str) -> str:
    """Render ``role``'s enforced frontmatter as YAML lines (no ``---``, no trailing newline)."""
    block = policy_native_keys(config, role)
    return yaml.safe_dump(block, sort_keys=False, default_flow_style=False).rstrip("\n")


def policy_gate_table(config: dict[str, Any]) -> list[dict[str, str]]:
    """Rows for the maestro's always-on risk/gate table at the active level.

    One row per category (the 4-category taxonomy): ``category`` id and the
    active level's ``gate`` with any ``policy.overrides``
    applied. ``strict`` shows the real ``deny`` row for ``dangerous``.
    """
    policy = config.get("policy") or {}
    level = policy.get("level", "guarded")
    overrides = policy.get("overrides") or {}
    cats = ("read", "local-write", "remote-write", "dangerous")
    gates = _gates_for(list(cats), level, overrides)
    return [{"category": cat, "gate": gates[cat]} for cat in cats]


def generate_default_config(
    workspace_name: str = "my-workspace",
    mode: str = "umbrella",
) -> dict[str, Any]:
    """Generate a default config dict for a new workspace."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["workspace"] = {"name": workspace_name, "mode": mode}
    # `guarded` is the floor and the DEFAULT_CONFIG value, so new
    # installs and existing/omitted configs both resolve to it — no per-install bump.
    return config


def write_config(config_path: Path, config: dict[str, Any]) -> None:
    """Write config dict to a YAML file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
