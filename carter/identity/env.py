"""``python -I -m carter.identity.env --json``: the 2a identity entry the plugin calls.

RFC-0007 App C.2 "T2 fail-closed", freeze G13. Stdlib-only (no ``carter.cli``, click or yaml).
It answers one question per agent shell: *must agent commits be blocked here?* The signing
block itself (keys, shim, ``GIT_COMMITTER_*``) arrives in slice 2b; until then an effective
tier of T2 means "blocked", never "unsigned".

Output (one JSON object, schema 1)::

    {"schema_version": 1, "tier": "t0|t1|t2", "cap": null|"t0"|"t1",
     "effective": "t0|t1|t2", "require_tier": null|"t0"|"t1"|"t2", "reason": ...}

``reason`` is ``null`` (nothing to do), ``config-error`` (config.toml unreadable, unknown
schema or an incomplete signing setup: E-CONFIG, commits are disabled until it is fixed),
``tier-required`` (a pinned ``require_tier`` or role ``author`` is not met) or
``signing-not-built`` (effective T2 before 2b). Only an *absent* file is T0 with no reason; a
schema-1 file is recognised and is T0 too. No value from the config is ever printed.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from carter.identity.config import ConfigError, default_path, load_identity
from carter.identity.errors import E_CONFIG, E_ROLE_B_TIER
from carter.identity.resolve import resolve
from carter.identity.schema import TIERS, IdentityConfig

SCHEMA_VERSION = 1


def workspace_for(cfg: IdentityConfig, cwd: str) -> str | None:
    """The pinned workspace key that contains ``cwd`` (longest match), or ``None``."""
    here = os.path.realpath(cwd)
    best: str | None = None
    for key in cfg.workspaces:
        root = os.path.realpath(key)
        inside = here == root or here.startswith(root.rstrip(os.sep) + os.sep)
        if inside and (best is None or len(root) > len(os.path.realpath(best))):
            best = key
    return best


def answer(
    cwd: str, env: Mapping[str, str] | None = None, config_path: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tier": "t0",
        "cap": None,
        "effective": "t0",
        "require_tier": None,
        "reason": None,
    }
    try:
        cfg = load_identity(Path(config_path) if config_path else default_path())
        res = resolve(cfg, workspace=workspace_for(cfg, cwd), env=env or {})
    except ConfigError:
        out["reason"] = "config-error"
        return out
    out.update(tier=res.configured_tier, cap=res.cap or None, effective=res.tier)
    out["require_tier"] = res.require_tier or None
    unmet = bool(res.require_tier) and TIERS.index(res.tier) < TIERS.index(res.require_tier)
    if res.refusal_reason == E_CONFIG:
        out["reason"] = "config-error"
    elif res.refusal_reason == E_ROLE_B_TIER or unmet:
        out["reason"] = "tier-required"
    elif res.tier == "t2":
        out["reason"] = "signing-not-built"
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--json" not in args:
        sys.stderr.write("usage: python -I -m carter.identity.env --json [--cwd DIR]\n")
        return 2
    cwd = args[args.index("--cwd") + 1] if "--cwd" in args else os.getcwd()
    sys.stdout.write(json.dumps(answer(cwd, os.environ)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
