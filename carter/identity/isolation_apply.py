"""Reference implementation of "apply the isolation block to an agent shell's environment".

The TypeScript plugin core (``carter/plugin/core.ts``) ports this function; the golden vectors in
``tests/data/plugin_vectors.json`` (section ``isolation``) are the contract both pass, so a change
here without the same change there fails a test. Plan 004 step 11; RFC-0007 App C.2.

Inputs are plain data: the environment the shell would inherit (a ``dict``), the loaded
``isolation.json`` document, and the GitHub read token text *already accepted* by the caller
(or ``None`` for the dummy). Returns the new environment and the status flag names (names only).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from carter.identity.pollution import count_state

_ENTRY_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


@dataclass
class Applied:
    env: dict[str, str]
    flags: list[str] = field(default_factory=list)


def apply_isolation(
    env: Mapping[str, str],
    iso: Mapping[str, Any],
    pat_text: str | None,
    *,
    block_commits: bool = False,
) -> Applied:
    """Return ``env`` with the isolation block applied; ``env`` itself is not modified.

    ``block_commits`` appends ``blocking_git_config`` (effective T2, or any identity failure).
    A polluted ``GIT_CONFIG_COUNT`` is replaced by a fresh count of 0 and also blocks commits."""
    out = dict(env)
    flags: list[str] = []
    counted = count_state(env)  # judged on the inherited environment, before any change
    polluted = counted.state == "polluted"
    for name in iso["env"]["delete"]:
        out.pop(name, None)
    out.update(iso["env"]["set"])
    if pat_text:
        out["GH_TOKEN"] = pat_text
    else:
        out["GH_TOKEN"] = iso["plugin"]["gh_token_dummy"]
        flags.append("pat-dummy")
    if polluted:
        for name in [n for n in out if n.startswith(_ENTRY_PREFIXES)]:
            del out[name]
        flags.append("count-malformed")
    entries = [list(p) for p in iso["git_config"]]
    if polluted or block_commits:
        entries += [list(p) for p in iso["blocking_git_config"]]
    n = counted.n
    for key, value in entries:  # appended after the inherited ones, so Carter's win a collision
        out[f"GIT_CONFIG_KEY_{n}"] = key
        out[f"GIT_CONFIG_VALUE_{n}"] = value
        n += 1
    out["GIT_CONFIG_COUNT"] = str(n)
    return Applied(out, flags)
