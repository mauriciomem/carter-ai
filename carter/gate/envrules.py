"""Rule ``env-overrides``: assignments, ``export``, ``unset``, ``env -u``.

The names come from the data file: the ``env-overrides`` items plus every ``isolation_vars`` name.
Reading a variable (``echo $HOME``) is not an override and never reaches this module.

A launcher variable (``PAGER``, ``GIT_EDITOR``, ``GH_BROWSER``...) names a program that git or gh
runs. It may be set to nothing or ``cat`` (the way to say "no pager"), never to anything else, and
never appended to (``+=``) or left to the shell to compute.
"""

from __future__ import annotations

from carter.gate.data import glob, rules
from carter.gate.unwrap import Eff, base
from carter.gate.words import Word

DECLARE = frozenset({"export", "declare", "typeset", "readonly", "local"})


def listed(name: str) -> bool:
    return any(glob(p, name) for p in rules()["env_names"])


def refused(name: str, value: str | None, append: bool) -> bool:
    """True when ``NAME=value`` is an override; ``value`` is None when absent or not literal."""
    if not listed(name):
        return False
    r = rules()
    return (
        append
        or value is None
        or name not in r["env_launchers"]
        or value not in r["env_launcher_values"]
    )


def assignment(w: Word) -> bool:
    """True when the assignment word ``NAME=value`` / ``NAME+=value`` is refused."""
    if w.assign is None:
        return False
    return refused(w.assign, w.value if w.static else None, w.text[w.value_at - 2] == "+")


def declared(arg: Word) -> bool:
    """True when an ``export``/``declare`` argument (``NAME[+]=value``) is refused."""
    name, eq, value = arg.text.partition("=")
    append = name.endswith("+")
    return refused(name.rstrip("+"), value if eq and arg.static else None, append)


def check(eff: Eff) -> bool:
    """True when ``eff`` assigns, exports or unsets a protected variable."""
    if any(assignment(w) for w in eff.assigns):
        return True
    if any(listed(n) for n in eff.unsets):
        return True
    if not eff.argv or not eff.argv[0].static:
        return False
    name, args = base(eff.argv[0]), eff.argv[1:]
    if name in DECLARE:
        return any(declared(a) for a in args if not a.text.startswith("-"))
    if name == "unset":
        return any(listed(a.text) for a in args if not a.text.startswith("-"))
    return False
