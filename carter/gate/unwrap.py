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
from carter.gate.wrappers import env, skip, time

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
STDIN_FILES = ("/dev/stdin", "/dev/fd/", "/proc/self/fd/")
# wrappers that run the words after them as a command line; with nothing after them (``xargs env``)
# the program comes from standard input
RUNNERS = frozenset(
    {"env", "command", "exec", "nohup", "setsid", "time", "nice", "ionice", "timeout", "stdbuf"}
    | {"unbuffer", "chronic", "watch"}
)


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
        self.from_stdin = False  # an xargs ran: it appends the words it reads to the command
        self.replace = ""  # xargs -I/-i/--replace string


def base(word: Word) -> str:
    return os.path.basename(word.text) if "/" in word.text else word.text


def interpreter_kind(name: str) -> str | None:
    if not INTERPRETERS.match(name):
        return None
    return re.sub(r"[0-9.]+\Z", "", name) or name


def _command(args: list[Word], eff: Eff) -> list[Word]:
    rest = args
    while rest and rest[0].text in ("-p", "--"):
        rest = rest[1:]
    if rest and rest[0].text in ("-v", "-V"):
        return []  # a lookup, nothing runs
    return rest


def _exec(args: list[Word], eff: Eff) -> list[Word]:
    return skip(args, "a")


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
    rest = skip(args, "InLPsdaE", long_valued)
    eff.from_stdin = True
    options = args[: len(args) - len(rest)]
    for i, w in enumerate(
        options
    ):  # the replacement string: `-I X`, `-IX`, `-i[X]`, `--replace[=X]`
        a = w.text
        if a in ("-I", "-J") and i + 1 < len(options):
            eff.replace = options[i + 1].text
        elif a.startswith(("-I", "-J", "-i")) and not a.startswith("--"):
            eff.replace = a[2:] or "{}"
        elif a.startswith("--replace"):
            eff.replace = a.partition("=")[2] or "{}"
    return rest


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


def _source(args: list[Word], eff: Eff) -> list[Word]:
    """``source``/``.`` runs a script in this shell: judge it like ``sh`` reading the same input."""
    target = args[0] if args else None
    if target is not None and target.text.startswith(("<(", *STDIN_FILES)):
        eff.stdin_shell = True
        eff.script_subst = target.text.startswith("<(")
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
    return skip(args, "sk", ("--signal", "--kill-after"), positional=1)


def _uv_run(args: list[Word], eff: Eff) -> list[Word]:
    if args and args[0].text == "run":
        return skip(
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
    "env": env,
    "command": _command,
    "builtin": lambda a, e: a,
    "exec": _exec,
    "nohup": lambda a, e: a,
    "setsid": lambda a, e: skip(a, ""),
    "time": time,
    "nice": lambda a, e: skip(a, "n", ("--adjustment",)),
    "ionice": lambda a, e: skip(a, "cnp"),
    "timeout": _timeout,
    "stdbuf": lambda a, e: skip(a, "ioe"),
    "unbuffer": lambda a, e: skip(a, ""),
    "chronic": lambda a, e: a,
    "xargs": _xargs,
    "watch": lambda a, e: skip(a, "ndp", ("--interval", "--differences")),
    "eval": _eval,
    "source": _source,
    ".": _source,
    "find": _find,
    "uv": _uv_run,
    "uvx": lambda a, e: skip(a, "p", ("--from", "--with", "--python")),
    "poetry": _sub_run,
    "pipenv": _sub_run,
    "pdm": _sub_run,
    "hatch": _sub_run,
    "npx": lambda a, e: skip(a, "p", ("--package",)),
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
        if eff.from_stdin and not argv and name in RUNNERS:
            eff.dynamic = True  # `xargs env`: stdin supplies the program
    else:  # more wrappers than MAX_WRAP: what runs is unknown, so refuse (never judge a prefix)
        eff.dynamic = True
    eff.argv = argv
    if eff.replace and stdin_names_program(eff):
        eff.dynamic = True
    return eff


def stdin_names_program(eff: Eff) -> bool:
    """``xargs -I{} {} ...`` or ``xargs -I{} sh -c '{}'``: the replaced word is what runs."""
    first = eff.argv[:1] + eff.nested_text
    return any(eff.replace in w.text for w in first)
