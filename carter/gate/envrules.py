"""Rule ``env-overrides``: assignments, ``export``, ``unset``, ``env -u``.

The names come from the data file: the ``env-overrides`` items plus every ``isolation_vars`` name.
Reading a variable (``echo $HOME``) is not an override and never reaches this module.
"""

from __future__ import annotations

from carter.gate.data import glob, rules
from carter.gate.unwrap import Eff, base

DECLARE = frozenset({"export", "declare", "typeset", "readonly", "local"})


def listed(name: str) -> bool:
    return any(glob(p, name) for p in rules()["env_names"])


def check(eff: Eff) -> bool:
    """True when ``eff`` assigns, exports or unsets a protected variable."""
    if any(w.assign is not None and listed(w.assign) for w in eff.assigns):
        return True
    if any(listed(n) for n in eff.unsets):
        return True
    if not eff.argv or not eff.argv[0].static:
        return False
    name, args = base(eff.argv[0]), eff.argv[1:]
    if name in DECLARE:
        return any(
            listed(a.text.split("=", 1)[0].lstrip("+")) for a in args if not a.text.startswith("-")
        )
    if name == "unset":
        return any(listed(a.text) for a in args if not a.text.startswith("-"))
    return False
