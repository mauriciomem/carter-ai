"""ANSI-C quoting (``$'...'``): the escapes bash decodes, so ``$'\\x67it'`` is seen as ``git``."""

from __future__ import annotations

import re

from carter.gate.words import ParseError

ANSI = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
}
HEX2 = re.compile(r"[0-9a-fA-F]{1,2}")
HEX8 = re.compile(r"[0-9a-fA-F]{1,8}")
OCT3 = re.compile(r"[0-7]{1,3}")


def decode_ansi_c(src: str, i: int) -> tuple[str, int]:
    """Decode from just after ``$'`` up to the closing quote; returns ``(text, index after it)``."""
    out: list[str] = []
    n = len(src)
    while i < n:
        c = src[i]
        if c == "'":
            return "".join(out), i + 1
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        nxt = src[i + 1]
        if nxt in ANSI:
            out.append(ANSI[nxt])
            i += 2
        elif nxt == "x" and (m := HEX2.match(src, i + 2)):
            out.append(chr(int(m.group(), 16)))
            i = m.end()
        elif nxt in "01234567" and (m := OCT3.match(src, i + 1)):
            out.append(chr(int(m.group(), 8) & 0xFF))
            i = m.end()
        elif nxt in "uU" and (m := HEX8.match(src, i + 2)):
            out.append(chr(min(int(m.group(), 16), 0x10FFFF)))
            i = m.end()
        else:
            out.append("\\" + nxt)
            i += 2
    raise ParseError("unterminated $'")
