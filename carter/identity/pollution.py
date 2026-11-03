"""Server-environment pollution and ``GIT_CONFIG_COUNT`` state (RFC-0007 App C.1, C.2).

Stdlib-only, like the rest of ``carter.identity``. Two pure functions, each with a shared
golden-vector table in ``tests/data/plugin_vectors.json`` that the TypeScript plugin core also
passes (``node --test``) so the two implementations cannot drift:

- ``pollution(env, home)``: names in an inherited environment that show it was started from an
  agent shell or that already carries Carter's isolation (App C.1 ``pollution_set``). Signals
  match by name, isolation markers only by Carter's exact value. ``SSH_AUTH_SOCK`` and other
  desktop values are never pollution, and ``GH_TOKEN``/``GITHUB_TOKEN`` only warrant a warning.
- ``count_state(env)``: whether an inherited ``GIT_CONFIG_COUNT`` can be appended to. Anything
  git would reject, or that git accepts but a strict parser should not (leading space, ``+1``),
  is ``polluted``: the plugin then starts a fresh count at 0 and appends the commit-blocking
  entries (C.2; spike E found that a bad count makes *every* git command fatal).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from carter.identity.rules import pollution_hits

COUNT_CAP = 1000
PAIR_MARKER_NAME = "GIT_CONFIG_KEY_n/GIT_CONFIG_VALUE_n"
_PAIR_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


@dataclass(frozen=True)
class CountState:
    state: str  # "ok" or "polluted"
    n: int  # entries to keep (0 when polluted: the plugin starts again at 0)
    reason: str = ""  # why polluted: malformed, over-cap, empty-with-keys, missing-entry, bad-key


def pollution(
    env: Mapping[str, str],
    home: str,
    *,
    pair_markers: Iterable[tuple[str, str]] | None = None,
) -> list[str]:
    """Names (never values) that make ``env`` polluted, signals first, in data-file order.

    ``pair_markers`` are Carter's isolation ``(key, value)`` entries; a ``GIT_CONFIG_KEY_i`` /
    ``GIT_CONFIG_VALUE_i`` pair equal to one of them marks the environment as already isolated.
    The default is the set the renderer publishes in ``isolation.json``."""
    if pair_markers is None:
        from carter.identity.isolation import pollution_pairs  # noqa: PLC0415 - avoids a cycle

        pair_markers = pollution_pairs(home)
    wanted = {tuple(p) for p in pair_markers}
    hits = pollution_hits(env, home=home)
    prefix = "GIT_CONFIG_KEY_"
    for name, key in env.items():
        index = name[len(prefix) :]
        if name.startswith(prefix) and index.isascii() and index.isdigit():
            value = env.get("GIT_CONFIG_VALUE_" + index)
            if value is not None and (key, value) in wanted:
                hits.append(PAIR_MARKER_NAME)
                break
    return hits


def count_state(env: Mapping[str, str]) -> CountState:
    """Strict reading of an inherited ``GIT_CONFIG_COUNT`` (cap ``COUNT_CAP``)."""
    raw = env.get("GIT_CONFIG_COUNT")
    if raw is None:
        return CountState("ok", 0)
    if raw == "":
        has_keys = any(name.startswith(_PAIR_PREFIXES) for name in env)
        return CountState("polluted", 0, "empty-with-keys") if has_keys else CountState("ok", 0)
    if not re.fullmatch(r"[0-9]+", raw):
        return CountState("polluted", 0, "malformed")
    if len(raw.lstrip("0")) > len(str(COUNT_CAP)) or int(raw) > COUNT_CAP:
        return CountState("polluted", 0, "over-cap")
    n = int(raw)
    for i in range(n):
        key, value = env.get(f"GIT_CONFIG_KEY_{i}"), env.get(f"GIT_CONFIG_VALUE_{i}")
        if key is None or value is None:
            return CountState("polluted", 0, "missing-entry")
        if "." not in key:
            return CountState("polluted", 0, "bad-key")
    return CountState("ok", n)
