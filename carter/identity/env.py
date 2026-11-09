"""``python -I -m carter.identity.env --json``: the identity entry the plugin calls per agent shell.

Stdlib-only (no ``carter.cli``, click or yaml). It answers one question per agent shell: *must
agent commits be blocked here, and if not, with which signing block?* The block itself is built by
``payload.build_payload``.

Output (one JSON object, schema 1)::

    {"schema_version": 1, "tier": "t0|t1|t2", "cap": null|"t0"|"t1",
     "effective": "t0|t1|t2", "require_tier": null|"t0"|"t1"|"t2", "reason": ...,
     "signing": {...}}                      <- only at effective t2 with reason null

``reason`` is ``null`` (nothing to do or a block follows), ``config-error`` (config.toml
unreadable, unknown schema or an incomplete signing setup: E-CONFIG), ``tier-required`` (a pinned
``require_tier`` or role ``author`` below T2 is not met), ``key-missing``, ``fingerprint-mismatch``,
``shim-missing`` or ``human-identity-invalid`` (role ``author``: the human's ``user.name`` /
``user.email`` in ``--cwd`` are empty, the LLM's or a Carter fallback; see ``payload``).
Only an *absent* file is T0 with no reason. The entry never probes the agent and never prints a
value from the config beyond the block itself (no key comment, no private-key path).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from carter.identity.coauthor import human_identity
from carter.identity.config import ConfigError, default_path, load_identity
from carter.identity.payload import ShimState, build_payload, shim_state
from carter.identity.resolve import resolve
from carter.identity.schema import IdentityConfig
from carter.identity.trailer import noreply_email

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
    cwd: str,
    env: Mapping[str, str] | None = None,
    config_path: str | None = None,
    home: Path | None = None,
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
    # Only a T2 setup needs the shim checked; below that no file is touched.
    shim = shim_state(home) if res.tier == "t2" else ShimState("", False)
    built = build_payload(
        cfg, res, shim, lambda: human_identity(cwd, noreply_email(cfg))
    )  # git is asked only for role `author`, after every other check passed
    out["reason"] = built.reason
    if built.block is not None:
        out["signing"] = built.block
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
