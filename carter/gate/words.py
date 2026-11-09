"""Data model of a parsed command line: words, redirections, heredocs, simple commands.

Plain ``__slots__`` classes on purpose: ``dataclasses`` pulls in ``inspect`` and costs 7 ms of
start-up, and the gate runs on every agent command.
"""

from __future__ import annotations

from collections.abc import Iterator

TYPE_CHECKING = False  # not ``from typing import TYPE_CHECKING``: that imports typing (1.4 ms)
if TYPE_CHECKING:
    from typing import Protocol


class ParseError(Exception):
    """The command cannot be parsed safely (unterminated quote, nesting too deep): refuse it."""


class Word:
    """One shell word after quote removal.

    ``text`` keeps unresolved expansions verbatim (``$x``, ``$(...)``) so that path checks can still
    see the literal parts around them. ``dynamic`` is set when an expansion could change the word.
    """

    __slots__ = ("assign", "brace", "dynamic", "glob", "quoted", "subs", "text", "value_at")

    def __init__(
        self,
        text: str = "",
        dynamic: bool = False,
        glob: bool = False,  # an unquoted * ? [set]: the shell may replace the word by file names
        brace: bool = False,  # an unquoted {a,b} or {1..3}: brace expansion
        quoted: bool = False,
        assign: str | None = None,  # NAME of a leading NAME=value (bare NAME, unquoted =)
        value_at: int = 0,
        subs: list[Cmd] | None = None,  # commands run by $(...), `...`, <(...)
    ) -> None:
        self.text, self.dynamic, self.glob, self.brace = text, dynamic, glob, brace
        self.quoted, self.assign, self.value_at = quoted, assign, value_at
        self.subs: list[Cmd] = subs if subs is not None else []

    @property
    def static(self) -> bool:
        return not (self.dynamic or self.glob or self.brace)

    @property
    def value(self) -> str:
        return self.text[self.value_at :]

    def __repr__(self) -> str:
        return f"Word({self.text!r})"


class Heredoc:
    __slots__ = ("body", "delim", "here_string", "quoted", "strip_tabs", "subs")

    def __init__(
        self,
        delim: str,
        quoted: bool,
        strip_tabs: bool = False,
        body: str = "",
        here_string: bool = False,  # <<< word
    ) -> None:
        self.delim, self.quoted, self.strip_tabs = delim, quoted, strip_tabs  # quoted: not expanded
        self.body, self.here_string = body, here_string
        self.subs: list[Cmd] = []  # substitutions of an unquoted body


class Cmd:
    """A simple command: prefix assignments, words, redirections, heredocs."""

    __slots__ = ("assigns", "discard", "heredocs", "pipe_in", "redirs", "words")

    def __init__(self, words: list[Word] | None = None) -> None:
        self.assigns: list[Word] = []
        self.words: list[Word] = words if words is not None else []
        self.redirs: list[tuple[str, Word]] = []
        self.heredocs: list[Heredoc] = []
        self.pipe_in = False  # the previous command in the pipeline feeds this one
        self.discard = False  # for/case/select heads: not a command

    def parts(self) -> Iterator[Word]:
        yield from self.assigns
        yield from self.words
        for _op, target in self.redirs:
            yield target

    def subcommands(self) -> Iterator[Cmd]:
        for word in self.parts():
            yield from word.subs
        for hd in self.heredocs:
            yield from hd.subs


if TYPE_CHECKING:

    class Judge(Protocol):
        """What the rule modules need from the engine (avoids an import cycle)."""

        cwd: str | None

        def deny(
            self, rule: str, hint: str | None = None, item_group: str | None = None
        ) -> None: ...

        def run_text(self, text: str, depth: int = 0) -> None: ...

        def run_words(self, words: list[Word], depth: int) -> None: ...

        def scan_code_paths(self, text: str) -> None: ...
