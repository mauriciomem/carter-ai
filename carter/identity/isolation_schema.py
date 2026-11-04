"""Schema check of ``isolation.json`` (G4, B9): exactly schema v2, anything else is invalid.

Schema 2 (slice B) adds the plugin keys for the broker tools. A plugin and a file of different
schemas refuse each other (``E-ISOLATION-MISSING``): they are installed together, so a mixed
pair means something was edited or half-installed, and agent shells are then not created.

Split from ``isolation.py`` to stay within the module size cap. The TypeScript core performs the
same checks on the same keys (``tests/plugin/isolation.test.ts``); any failure there or here
means ``E-ISOLATION-MISSING``: the agent shell is not created. Error details name keys, never
values.
"""

from __future__ import annotations

import os
from typing import Any

from carter.identity.errors import E_ISOLATION_MISSING, IdentityError
from carter.identity.policyset import consent_groups

SCHEMA_VERSION = 2  # slice B: plugin.{b_enabled, b_caller, broker_args, b_git, b_gh}
TOP_KEYS = frozenset(
    {"schema_version", "env", "git_config", "blocking_git_config", "pollution", "plugin"}
)
PLUGIN_KEYS = frozenset(
    {
        "python_path",
        "carter_path",
        "gate_args",
        "env_args",
        "pat_file",
        "pat_prefix",
        "gh_token_dummy",
        "declined_groups",
        "self_test_ms",
        "gate_timeout_ms",
        "env_timeout_ms",
        "status_dir",
        "b_enabled",
        "b_caller",
        "broker_args",
        "b_git",
        "b_gh",
    }  # fmt: skip
)


def _bad(why: str) -> IdentityError:
    return IdentityError(E_ISOLATION_MISSING, detail=why)  # `why` names a key, never a value


def _strs(value: Any, what: str) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _bad(f"{what} must be a list of strings")


def _pairs(value: Any, what: str) -> None:
    ok = isinstance(value, list) and all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p) for p in value
    )
    if not ok:
        raise _bad(f"{what} must be a list of [key, value] pairs")


def validate(doc: Any) -> None:
    """Raise ``IdentityError(E-ISOLATION-MISSING)`` unless ``doc`` is exactly schema v2."""
    if not isinstance(doc, dict) or set(doc) != TOP_KEYS:
        raise _bad("top-level keys")
    if doc["schema_version"] != SCHEMA_VERSION or isinstance(doc["schema_version"], bool):
        raise _bad("schema_version")
    env = doc["env"]
    if not isinstance(env, dict) or set(env) != {"set", "delete"}:
        raise _bad("env keys")
    if not isinstance(env["set"], dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env["set"].items()
    ):
        raise _bad("env.set")
    _strs(env["delete"], "env.delete")
    _pairs(doc["git_config"], "git_config")
    _pairs(doc["blocking_git_config"], "blocking_git_config")
    poll = doc["pollution"]
    if not isinstance(poll, dict) or set(poll) != {"agent_signals", "human_signals", "markers"}:
        raise _bad("pollution keys")
    _strs(poll["agent_signals"], "pollution.agent_signals")
    _strs(poll["human_signals"], "pollution.human_signals")
    markers = poll["markers"]
    if not isinstance(markers, dict) or set(markers) != {"env", "git_config"}:
        raise _bad("pollution.markers keys")
    if not isinstance(markers["env"], list) or not all(
        isinstance(m, list) and len(m) == 3 and all(isinstance(x, str) for x in m)
        for m in markers["env"]
    ):
        raise _bad("pollution.markers.env")
    _pairs(markers["git_config"], "pollution.markers.git_config")
    plugin = doc["plugin"]
    if not isinstance(plugin, dict) or set(plugin) != PLUGIN_KEYS:
        raise _bad("plugin keys")
    for key in ("python_path", "carter_path", "status_dir"):
        if not isinstance(plugin[key], str) or not os.path.isabs(plugin[key]):
            raise _bad(f"plugin.{key} must be an absolute path")
    if not isinstance(plugin["pat_file"], str) or (
        plugin["pat_file"] and not os.path.isabs(plugin["pat_file"])
    ):
        raise _bad("plugin.pat_file must be empty or an absolute path")
    for key in ("gate_args", "env_args", "declined_groups"):
        _strs(plugin[key], f"plugin.{key}")
    if not set(plugin["declined_groups"]) <= {g.id for g in consent_groups()}:
        raise _bad("plugin.declined_groups holds an unknown group")
    for key in ("pat_prefix", "gh_token_dummy"):
        if not isinstance(plugin[key], str) or not plugin[key]:
            raise _bad(f"plugin.{key}")
    for key in ("self_test_ms", "gate_timeout_ms", "env_timeout_ms"):
        if not isinstance(plugin[key], int) or isinstance(plugin[key], bool) or plugin[key] <= 0:
            raise _bad(f"plugin.{key} must be a positive integer")
    _validate_broker(plugin)


def _validate_broker(plugin: dict[str, Any]) -> None:
    if not isinstance(plugin["b_enabled"], bool):
        raise _bad("plugin.b_enabled must be true or false")
    if not isinstance(plugin["b_caller"], str) or not plugin["b_caller"]:
        raise _bad("plugin.b_caller must be a non-empty string")
    _strs(plugin["broker_args"], "plugin.broker_args")
    for key in ("b_git", "b_gh"):
        value = plugin[key]
        if not isinstance(value, str) or (value and not os.path.isabs(value)):
            raise _bad(f"plugin.{key} must be empty or an absolute path")
    if plugin["b_enabled"] and not plugin["b_git"]:
        raise _bad("plugin.b_git is needed while plugin.b_enabled is true")
