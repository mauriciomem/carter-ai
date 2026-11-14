"""The wrappers that need more than a line to peel: option skipping, ``env`` and ``time``."""

from __future__ import annotations

from carter.gate.words import Word

TYPE_CHECKING = False
if TYPE_CHECKING:
    from carter.gate.unwrap import Eff


def skip(
    args: list[Word], valued: str | set[str], long_valued: tuple[str, ...] = (), positional: int = 0
) -> list[Word]:
    """Skip options (those in ``valued`` take a value) then ``positional`` leading words."""
    i = 0
    while i < len(args):
        a = args[i].text
        if a == "--":
            i += 1
            break
        if not a.startswith("-") or a == "-":
            break
        if a.startswith("--"):
            i += 2 if a in long_valued else 1
        elif len(a) == 2 and a[1] in valued:
            i += 2
        else:
            i += 1  # a flag cluster or an option with an attached value
    return args[i + positional :]


def env(args: list[Word], eff: Eff) -> list[Word]:
    i, options = 0, True  # after `--` the options end, but NAME=value words are still assignments
    while i < len(args):
        a = args[i].text
        nxt = args[i + 1] if i + 1 < len(args) else None
        if args[i].assign is not None:
            eff.assigns.append(args[i])
            i += 1
        elif not options:
            return args[i:]
        elif a == "--":
            options = False
            i += 1
        elif a in ("-u", "--unset") and nxt is not None:
            eff.unsets.append(nxt.text)
            i += 2
        elif a.startswith("--unset="):
            eff.unsets.append(a[8:])
            i += 1
        elif a.startswith("-u") and len(a) > 2 and not a.startswith("--"):
            eff.unsets.append(a[2:])
            i += 1
        elif a in ("-C", "--chdir") and nxt is not None:
            i += 2
        elif a in ("-S", "--split-string") and nxt is not None:
            eff.nested_text.append(nxt)
            i += 2
        elif a.startswith("--split-string=") or (
            a.startswith("-S") and len(a) > 2 and not a.startswith("--")
        ):
            eff.nested_text.append(
                Word(text=a.split("=", 1)[1] if a.startswith("--") else a[2:], quoted=True)
            )
            i += 1
        elif a.startswith("-"):
            i += 1
        else:
            return args[i:]
    return []


def time(args: list[Word], eff: Eff) -> list[Word]:
    """bash's ``time`` keyword takes prefix assignments (``time NAME=v cmd``)."""
    rest = skip(args, "of", ("--format", "--output"))
    i = 0
    while i < len(rest) and rest[i].assign is not None:
        eff.assigns.append(rest[i])
        i += 1
    return rest[i:]
