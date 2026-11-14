"""A fake terminal pair for the report snapshots: one ordered transcript for stdout and stderr.

``Term(kind)`` builds the (out, err) streams ``carter.ui`` writes to. Both append to one list, so
the combined text is what a human reads with ``2>&1``.

kinds: ``tty`` (UTF-8 terminal), ``pipe`` (UTF-8, not a terminal), ``ascii`` (not a terminal and
not UTF-8: a character outside ASCII raises, as on a real strict stream).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class _Stream:
    def __init__(self, name: str, term: Term) -> None:
        self.name = name
        self.term = term
        self.encoding = "ascii" if term.kind == "ascii" else "utf-8"

    def isatty(self) -> bool:
        return self.term.kind == "tty"

    def write(self, text: str) -> int:
        if self.encoding == "ascii":
            text.encode("ascii", "strict")
        self.term.chunks.append((self.name, text))
        return len(text)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:  # rich asks; a fake terminal has none
        raise OSError("no fileno")


@dataclass
class Term:
    kind: str = "tty"
    chunks: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.out = _Stream("out", self)
        self.err = _Stream("err", self)

    def text(self, which: str = "both") -> str:
        return "".join(t for name, t in self.chunks if which in ("both", name))

    def routed(self) -> str:
        """Each line prefixed by the stream it went to (colour removed)."""
        lines = []
        for name, text in self.chunks:
            lines += [f"{name:<3} | {line}".rstrip() for line in ANSI.sub("", text).splitlines()]
        return "\n".join(lines) + "\n"
