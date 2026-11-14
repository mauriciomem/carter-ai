"""Rule ``env-overrides``: assignments, ``export``, ``unset``, ``env -u``.

The names come from the data file: the ``env-overrides`` items plus every ``isolation_vars`` name.
Reading a variable (``echo $HOME``) is not an override and never reaches this module.

A launcher variable (``PAGER``, ``GIT_EDITOR``, ``GH_BROWSER``...) names a program that git or gh
runs. It may be set to nothing, ``cat``, ``true`` or ``:`` (the ways to say "no pager, no editor"),
never to anything else, and never appended to (``+=``) or left to the shell to compute. Unsetting
one is fine: git and gh then fall back to their defaults.

Every way bash has to write a variable counts: ``NAME=v``, the declaration builtins, ``read``,
``printf -v``, ``for NAME in``, ``${NAME:=v}`` and namerefs (``declare -n``).
"""

from __future__ import annotations

import re

from carter.gate.data import glob, rules
from carter.gate.unwrap import Eff, base
from carter.gate.words import Word

DECLARE = frozenset({"export", "declare", "typeset", "readonly", "local"})
NAMEREF = frozenset({"declare", "typeset", "local"})  # `-n` makes the name a reference to another
DEFAULT_ASSIGN = re.compile(r"\$\{(\w+)(?:\[[^\]]*\])?:?=")  # ${NAME:=v} and ${NAME=v}
COMPUTED = "$`*?[{"  # a name written with these is not known until the shell expands it


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


def unsettable(name: str) -> bool:
    """True when unsetting ``name`` is an override (every listed name but the launchers)."""
    return listed(name) and name not in rules()["env_launchers"]


def assignment(w: Word) -> bool:
    """True when the assignment word ``NAME=value`` / ``NAME+=value`` is refused."""
    if w.assign is None:
        return False
    return refused(w.assign, w.value if w.static else None, w.text[w.value_at - 2] == "+")


def declared(arg: Word) -> bool:
    """True when an ``export``/``declare`` argument (``NAME[+]=value``) is refused."""
    name, eq, value = arg.text.partition("=")
    if any(c in name for c in COMPUTED):  # `export $x=v`: x may hold a launcher name
        return True
    return refused(name.removesuffix("+"), value if eq and arg.static else None, name.endswith("+"))


def written(w: Word) -> bool:
    """True when a builtin that stores input or output in ``w`` could write a listed name."""
    return not w.static or listed(w.text)


def printf_targets(args: list[Word]) -> list[Word]:
    """The names given to ``printf -v NAME`` (also ``-vNAME``)."""
    found = []
    for i, w in enumerate(args):
        if w.text == "-v" and i + 1 < len(args):
            found.append(args[i + 1])
        elif w.text.startswith("-v") and len(w.text) > 2:
            found.append(Word(text=w.text[2:], dynamic=w.dynamic))
    return found


def expands_default(eff: Eff) -> bool:
    """True for ``${NAME:=v}`` / ``${NAME=v}`` on a listed name anywhere in the command."""
    texts = [w.text for w in eff.cmd.parts()] + [h.body for h in eff.cmd.heredocs if not h.quoted]
    return any(listed(m[1]) for t in texts for m in DEFAULT_ASSIGN.finditer(t))


def builtin(name: str, args: list[Word]) -> bool:
    """True when the shell builtin ``name`` overrides a listed variable."""
    plain = [a for a in args if not a.text.startswith("-")]
    if name in DECLARE:
        if name in NAMEREF and any(a.text.startswith("-") and "n" in a.text[1:] for a in args):
            return True
        return any(declared(a) for a in plain)
    if name == "unset":
        return any(unsettable(a.text) for a in plain)
    if name == "read":
        return any(written(a) for a in plain)
    if name == "printf":
        return any(written(a) for a in printf_targets(args))
    return False


def check(eff: Eff) -> bool:
    """True when ``eff`` assigns, exports or unsets a protected variable."""
    if any(assignment(w) for w in eff.assigns) or any(unsettable(n) for n in eff.unsets):
        return True
    if expands_default(eff):
        return True
    if not eff.argv or not eff.argv[0].static:
        return False
    return builtin(base(eff.argv[0]), eff.argv[1:])
