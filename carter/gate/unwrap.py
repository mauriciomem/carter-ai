"""Peel the wrappers off a simple command.

``env``, ``command``, ``exec``, ``nohup``, ``time``, ``xargs``, ``sh -c`` and friends all end in
"run this other command". The gate must judge that command, not the wrapper. ``unwrap`` returns
what really runs (``Eff.argv``), the assignments and unsets the wrappers apply, and any command
strings or argument lists that run nested (``sh -c STRING``, ``eval``, ``find -exec``).
A command word the shell would compute (a variable, a substitution, a glob) sets ``dynamic``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

from carter.gate.words import Cmd, Word

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh", "csh", "tcsh", "fish"})
INTERPRETERS = re.compile(
    r"(python[0-9.]*|pypy[0-9]*|perl[0-9.]*|ruby[0-9.]*|node(js)?|deno|bun|php[0-9.]*|lua[0-9.]*|g?awk|mawk|nawk|osascript|tclsh|Rscript)\Z"
)
# interpreter flag letters whose next word is program text
CODE_FLAGS = {
    "python": "c",
    "pypy": "c",
    "perl": "eE",
    "ruby": "e",
    "node": "ep",
    "nodejs": "ep",
    "php": "r",
    "lua": "e",
    "osascript": "e",
    "Rscript": "e",
    "deno": "e",
}
MAX_WRAP = 12


class Eff:
    """What a simple command really runs."""

    def __init__(self, cmd: Cmd) -> None:
        self.cmd = cmd
        self.argv: list[Word] = []
        self.assigns: list[Word] = list(cmd.assigns)
        self.unsets: list[str] = []
        self.nested_text: list[Word] = []  # strings parsed as command lines
        self.nested_argv: list[list[Word]] = []  # find -exec ... ;
        self.shell = ""  # set when the effective command is a shell
        self.stdin_shell = False  # a shell with no -c and no script file: program from stdin
        self.script_subst = False  # a shell whose script is a <(...) substitution
        self.dynamic = False


def base(word: Word) -> str:
    return os.path.basename(word.text) if "/" in word.text else word.text


def interpreter_kind(name: str) -> str | None:
    if not INTERPRETERS.match(name):
        return None
    return re.sub(r"[0-9.]+\Z", "", name) or name


def _skip(
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


def _env(args: list[Word], eff: Eff) -> list[Word]:
    i = 0
    while i < len(args):
        a = args[i].text
        nxt = args[i + 1] if i + 1 < len(args) else None
        if a == "--":
            return args[i + 1 :]
        if a in ("-u", "--unset") and nxt is not None:
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
        elif args[i].assign is not None:
            eff.assigns.append(args[i])
            i += 1
        elif a.startswith("-") and a != "-" or a == "-":
            i += 1
        else:
            return args[i:]
    return []


def _command(args: list[Word], eff: Eff) -> list[Word]:
    rest = args
    while rest and rest[0].text in ("-p", "--"):
        rest = rest[1:]
    if rest and rest[0].text in ("-v", "-V"):
        return []  # a lookup, nothing runs
    return rest


def _exec(args: list[Word], eff: Eff) -> list[Word]:
    return _skip(args, "a")


def _xargs(args: list[Word], eff: Eff) -> list[Word]:
    long_valued = (
        "--max-args",
        "--max-lines",
        "--max-procs",
        "--max-chars",
        "--delimiter",
        "--arg-file",
        "--eof",
        "--process-slot-var",
    )
    return _skip(args, "InLPsdaE", long_valued)


def _shell(name: str) -> Callable[[list[Word], Eff], list[Word]]:
    def handler(args: list[Word], eff: Eff) -> list[Word]:
        eff.shell = name
        i = 0
        while i < len(args):
            a = args[i].text
            if a == "--":
                i += 1
                break
            if a in ("-o", "+o", "--rcfile", "--init-file") or (a in ("-O", "+O")):
                i += 2
            elif re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", a):
                if i + 1 < len(args):
                    eff.nested_text.append(args[i + 1])
                return []
            elif a.startswith("-") or a.startswith("+"):
                i += 1
            else:
                break
        if i < len(args):  # a script file: not inspected (accepted residual)
            eff.script_subst = bool(args[i].subs) and args[i].text.startswith("<(")
            eff.stdin_shell = eff.script_subst
            return []
        eff.stdin_shell = True
        return []

    return handler


def _eval(args: list[Word], eff: Eff) -> list[Word]:
    if args:
        eff.nested_text.append(
            Word(
                text=" ".join(a.text for a in args),
                dynamic=any(a.dynamic for a in args),
                quoted=True,
            )
        )
    return []


def _find(args: list[Word], eff: Eff) -> list[Word]:
    i = 0
    while i < len(args):
        if args[i].text in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            while j < len(args) and args[j].text not in (";", "+"):
                j += 1
            eff.nested_argv.append(args[i + 1 : j])
            i = j
        i += 1
    return []  # find itself is judged by the caller (it is still a command)


def _timeout(args: list[Word], eff: Eff) -> list[Word]:
    return _skip(args, "sk", ("--signal", "--kill-after"), positional=1)


def _uv_run(args: list[Word], eff: Eff) -> list[Word]:
    if args and args[0].text == "run":
        return _skip(
            args[1:],
            "pP",
            (
                "--with",
                "--with-requirements",
                "--python",
                "--directory",
                "--project",
                "--env-file",
                "--extra",
                "--group",
                "--package",
                "--index",
                "--with-editable",
            ),
        )
    return []


def _sub_run(args: list[Word], eff: Eff) -> list[Word]:
    return args[1:] if args and args[0].text == "run" else []


WRAPPERS = {
    "env": _env,
    "command": _command,
    "builtin": lambda a, e: a,
    "exec": _exec,
    "nohup": lambda a, e: a,
    "setsid": lambda a, e: _skip(a, ""),
    "time": lambda a, e: _skip(a, "of", ("--format", "--output")),
    "nice": lambda a, e: _skip(a, "n", ("--adjustment",)),
    "ionice": lambda a, e: _skip(a, "cnp"),
    "timeout": _timeout,
    "stdbuf": lambda a, e: _skip(a, "ioe"),
    "unbuffer": lambda a, e: _skip(a, ""),
    "chronic": lambda a, e: a,
    "xargs": _xargs,
    "watch": lambda a, e: _skip(a, "ndp", ("--interval", "--differences")),
    "eval": _eval,
    "find": _find,
    "uv": _uv_run,
    "uvx": lambda a, e: _skip(a, "p", ("--from", "--with", "--python")),
    "poetry": _sub_run,
    "pipenv": _sub_run,
    "pdm": _sub_run,
    "hatch": _sub_run,
    "npx": lambda a, e: _skip(a, "p", ("--package",)),
    **{s: _shell(s) for s in SHELLS},
}
KEEPS_COMMAND = frozenset(
    {"find"}
)  # the wrapper is itself a command whose arguments are still judged


def unwrap(cmd: Cmd) -> Eff:
    eff = Eff(cmd)
    argv = list(cmd.words)
    for _ in range(MAX_WRAP):
        if not argv:
            break
        head = argv[0]
        if not head.static:
            eff.dynamic = True
            break
        name = base(head)
        handler = WRAPPERS.get(name)
        if handler is None:
            break
        if name in KEEPS_COMMAND:
            handler(argv[1:], eff)
            break
        argv = handler(argv[1:], eff)
    else:  # more wrappers than MAX_WRAP: what runs is unknown, so refuse (never judge a prefix)
        eff.dynamic = True
    eff.argv = argv
    return eff
