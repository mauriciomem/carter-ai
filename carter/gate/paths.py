"""Credential and control paths after normalization (RFC-0007 C.4.2 rule 8, freeze G9, D67).

A token is normalized before it is matched: ``~`` and ``$HOME`` are already expanded by the lexer,
relative tokens are resolved against the effective directory (``cd`` and ``git -C`` are tracked),
``.`` and ``..`` are collapsed, braces and globs are expanded, and one ``realpath`` per candidate
catches symlinks. Matching is on path *segments*, so ``~/.sshfoo`` is not ``/.ssh/``.

Credential paths are refused for any reference by any command. Control paths are refused only for
write-capable references (redirections, ``tee``, ``sed -i``, ``cp``/``mv``/``rm``/``ln``/``chmod``/
``truncate``..., interpreter arguments); reads such as ``cat ~/.carter/gitconfig`` pass. D67: the
other section 4.5 paths (global OpenCode config, ``~/.gitconfig``, repo ``.opencode/``,
``.git/hooks``,
``.git/config``...) are an accepted residual; the corpus pins them as allowed.
"""

from __future__ import annotations

import os
import re

from carter.gate.data import glob as gmatch
from carter.gate.data import rules
from carter.gate.unwrap import Eff, base, interpreter_kind
from carter.gate.words import ParseError, Word

WRITE_REDIRS = frozenset({">", ">>", ">|", "&>", "&>>", "<>", ">&"})
RECURSIVE_FLAGS = re.compile(r"-[A-Za-z]*[rRa]|--recursive\Z|--archive\Z")
SED_INPLACE = re.compile(r"-[A-Za-z]*i|--in-place")
MAX_BRACE = 1024  # more alternatives than this is refused, never truncated (a cut-off hides paths)
MAX_GLOB = 20000  # same for glob matches
FS_BUDGET = 3000  # realpath calls per command; past it only the string checks run (G-residual)


def segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s not in ("", ".")]


def contains_seq(have: list[str], want: list[str]) -> bool:
    n = len(want)
    return any(
        all(gmatch(want[j], have[i + j]) for j in range(n)) for i in range(len(have) - n + 1)
    )


def braces(text: str) -> list[str]:
    """Expand ``{a,b}`` groups (not ranges); more than ``MAX_BRACE`` results is refused."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", text)
    if not m:
        return [text]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out += braces(text[: m.start()] + alt + text[m.end() :])
        if len(out) > MAX_BRACE:
            raise ParseError("brace expansion too large")
    return out


def expand_glob(path: str) -> list[str]:
    """Expand glob segments against the file system (directories only; a segment with no match
    stays literal, so ``~/.ss*/x`` still names ``.ssh`` when ``x`` does not exist yet).
    A hidden match must never be cut off, so more than ``MAX_GLOB`` matches is refused."""
    if not re.search(r"[*?\[]", path):
        return [path]
    import fnmatch  # noqa: PLC0415 - only for words that contain glob characters

    prefixes = ["/" if path.startswith("/") else ""]
    for seg in segments(path):
        nxt: list[str] = []
        for pre in prefixes:
            if re.search(r"[*?\[]", seg):
                try:
                    names = sorted(n for n in os.listdir(pre or ".") if fnmatch.fnmatchcase(n, seg))
                except OSError:
                    names = []
                nxt += [os.path.join(pre, n) for n in names] or [os.path.join(pre, seg)]
            else:
                nxt.append(os.path.join(pre, seg))
            if len(nxt) > MAX_GLOB:
                raise ParseError("glob expansion too large")
        prefixes = nxt
    return prefixes


class Paths:
    def __init__(self, home: str, cwd: str | None) -> None:
        self.home = home
        self.real_home = os.path.realpath(home)
        self.cwd = cwd
        self.fs_calls = 0
        self.memo: dict[str, list[str]] = {}
        r = rules()
        self.credential = r["credential"]
        self.control = [self.anchored(p) for p in r["control"]]

    def anchored(self, entry: str) -> tuple[str, bool]:
        """``(absolute path without trailing slash, is_directory)`` for a ``~/``-relative entry."""
        return os.path.normpath(self.home + entry[1:]), entry.endswith("/")

    def candidates(self, word: Word) -> list[str]:
        """Path-like strings a word may stand for (whole word, text after ``=``, ``:`` or ``,``)."""
        text = word.text
        flag_only = text.startswith("--") or (text.startswith("-") and "/" not in text)
        if not text or (flag_only and "=" not in text) or re.search(r"\s", text):
            return []
        pieces = {text}
        if "=" in text:
            pieces.add(text.split("=", 1)[1])
        if text.startswith("-") and not text.startswith("--") and len(text) > 2:
            pieces.add(text[2:])  # -i/path: a short option with its value attached
        for piece in list(pieces):
            pieces.update(p for p in re.split(r"[:,]", piece) if p)
        out: list[str] = []
        for piece in pieces:
            piece = piece.lstrip("-") if piece.startswith("-") else piece
            if piece.startswith("~/") or piece == "~":
                piece = self.home + piece[1:]
            out += braces(piece) if word.brace else [piece]
        return out

    def resolve(self, token: str) -> list[str]:
        """Absolute (or segment-only, when no base is known) forms of ``token`` to match."""
        if token in self.memo:
            return self.memo[token]
        forms: list[str] = []
        self.memo[token] = forms
        for t in expand_glob(token):
            if t.startswith("/"):
                path = os.path.normpath(t)
            elif self.cwd:
                path = os.path.normpath(os.path.join(self.cwd, t))
            else:
                forms.append(os.path.normpath(t))  # relative, no base: segments only
                continue
            forms.append(path)
            self.fs_calls += 1
            real = os.path.realpath(path) if self.fs_calls <= FS_BUDGET else path
            if real != path:
                forms.append(real)
        return forms

    def is_credential(self, word: Word) -> bool:
        for token in self.candidates(word):
            for form in self.resolve(token):
                have = segments(form)
                if any(contains_seq(have, want) for want in self.credential):
                    return True
        return False

    def control_hit(self, form: str, recursive: bool) -> bool:
        for path, is_dir in self.control:
            for root in {
                path,
                os.path.normpath(self.real_home + path[len(self.home) :])
                if path.startswith(self.home)
                else path,
            }:
                if form == root or (is_dir and form.startswith(root + "/")):
                    return True
                if recursive and root.startswith(form.rstrip("/") + "/"):
                    return True
        return False

    def is_control_write(self, word: Word, recursive: bool = False) -> bool:
        return any(
            self.control_hit(f, recursive)
            for t in self.candidates(word)
            for f in self.resolve(t)
            if f.startswith("/")
        )

    def code_mentions_control(self, text: str) -> bool:
        tails = [p[2:].rstrip("/") for p in rules()["control"]]
        return any(re.search(r"(?<![\w.])" + re.escape(t) + r"(?![\w-])", text) for t in tails)

    def code_mentions_credential(self, text: str) -> bool:
        """Credential paths named inside program text (``open('~/.ssh/id')``)."""
        for want in self.credential:
            body = "/".join("[^/\\s'\"]+" if seg == "*" else re.escape(seg) for seg in want)
            if re.search(r"(?:^|[/'\"\s~=:])" + body + r"(?:$|[/'\"\s:])", text):
                return True
        return False


def write_targets(eff: Eff) -> list[tuple[Word, bool]]:
    """``(word, recursive)`` pairs the command writes to, by command name."""
    argv = eff.argv
    if not argv or not argv[0].static:
        return []
    name, args = base(argv[0]), argv[1:]
    if name not in rules()["control_cmds"]:
        return []
    flags = [a.text for a in args if a.text.startswith("-")]
    pos = [
        a
        for a in args
        if not a.text.startswith("-")
        and not a.dynamic
        or (not a.text.startswith("-") and a.dynamic)
    ]
    recursive = any(RECURSIVE_FLAGS.match(f) for f in flags)
    if name == "sed":
        return [(a, False) for a in pos] if any(SED_INPLACE.match(f) for f in flags) else []
    if name in ("rm", "mv", "rmdir", "unlink", "shred"):
        return [(a, True) for a in pos]
    if name in ("cp", "install", "rsync", "ln"):
        target = [
            a for i, a in enumerate(args) if i and args[i - 1].text in ("-t", "--target-directory")
        ]
        dest = target or pos[-1:]
        return [(a, recursive or name == "rsync") for a in dest]
    if name in ("chmod", "chown", "chgrp"):
        return [(a, recursive) for a in pos[1:]]
    if name == "dd":
        return [(Word(text=a.text[3:]), False) for a in args if a.text.startswith("of=")]
    return [(a, False) for a in pos]


def interpreter_args(eff: Eff) -> list[Word]:
    if eff.argv and eff.argv[0].static and interpreter_kind(base(eff.argv[0])):
        return eff.argv[1:]
    return []
