"""The gate's view of ``g2_rules.json``, read by file path (no ``carter.identity`` import).

Importing ``carter.identity`` would pull ``config``, ``errors`` and ``importlib.resources`` (about
25 ms), and the gate runs on every agent shell command. The single data file stays
the only source of every list: this module only reshapes it into what the rules need.
"""

from __future__ import annotations

import json
import os

TYPE_CHECKING = False  # not from typing: importing typing costs 1.4 ms
if TYPE_CHECKING:
    from typing import Any

PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "identity", "g2_rules.json"
)
_cache: dict[str, Any] = {}


def glob(pattern: str, text: str) -> bool:
    """``*`` matches any run of characters; everything else is literal. Case-sensitive."""
    parts = pattern.split("*")
    if len(parts) == 1:
        return pattern == text
    if not text.startswith(parts[0]) or not text.endswith(parts[-1]):
        return False
    pos = len(parts[0])
    end = len(text) - len(parts[-1])
    for mid in parts[1:-1]:
        found = text.find(mid, pos, end)
        if found < 0:
            return False
        pos = found + len(mid)
    return pos <= end


def rules() -> dict[str, Any]:
    if not _cache:
        with open(PATH, encoding="utf-8") as f:
            raw = json.load(f)
        _cache.update(build(raw))
    return _cache


def build(raw: dict[str, Any]) -> dict[str, Any]:
    cls = {e["id"]: e for e in raw["forbidden"]}
    gate_hints = {e["id"]: e["hint"] for e in raw["gate_rules"]}
    commit, other, ctl = cls["commit-flags"], cls["other-verbs"], cls["control-files"]
    long_flags = [
        i for i in commit["items"] if i.startswith("--") and "<" not in i and "=" not in i
    ]
    humans = []
    for item in cls["human-only-carter"]["items"]:
        words = item.split()
        sub = words[2] if len(words) > 2 else "*"
        humans.append((words[1], tuple(sub.split("/")) if sub != "*" else None))
    staging: list[tuple[str, str]] = []
    for item in cls["staging"]["items"]:
        _git, verb, arg = item.split()
        staging.append((verb, arg))
    single = [i for i in other["items"] if " " not in i] + other["gate_extra"]
    groups = {"credential-paths": cls["credential-paths"]["group"], "control-files": ctl["group"]}
    return {
        "hints": {**{i: c["hint"] for i, c in cls.items()}, **gate_hints},
        "group_of": {i: c["group"] for i, c in cls.items()},
        "item_groups": dict(other.get("item_groups", {})),
        "env_names": list(cls["env-overrides"]["items"]) + list(raw["isolation_vars"]),
        "config_keys": [
            k.lower() for k in cls["config-flags"]["items"] + cls["config-flags"]["gate_keys"]
        ],
        "commit_verbs": set(commit["verbs"]),
        "commit_long": long_flags,
        "no_verify_short": {
            v for f in commit["scoped_flags"] if f["flag"] == "-n" for v in f["verbs"]
        },
        "signoff_short": set(commit["signoff_short_verbs"]),
        "staging": staging,
        "push_verbs": set(cls["push-verbs"]["gate_verbs"]),
        "push_pairs": [tuple(p) for p in cls["push-verbs"]["gate_pairs"]],
        "plumbing": set(cls["plumbing"]["items"]),
        "other_single": set(single),
        "opencode_verbs": {i.split()[1] for i in other["items"] if i.startswith("opencode ")},
        "opencode_service": set(other["gate_opencode_service"]),
        "human_only": humans,
        "gh_allow": [tuple(e["verb"].split()) for e in raw["gh_read_allowlist"]],
        "credential": [p.strip("/").split("/") for p in raw["credential_paths"]],
        "security_items": [
            i for i in cls["credential-paths"]["items"] if i.startswith("security ")
        ],
        "control": list(raw["control_paths"]),
        "control_cmds": set(ctl["gate_extra_commands"]) | {i.split()[0] for i in ctl["items"]},
        "rule_groups": groups,
    }
