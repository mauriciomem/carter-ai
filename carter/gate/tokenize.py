"""Shell lexer and command builder for the gate.

``shlex`` cannot answer the questions the gate asks (which words are code, which are data, what
runs inside ``$(...)``), so this is a small explicit scanner: quotes, escapes, ``$'...'``,
``$(...)``, backticks, ``${...}``, ``<(...)``, heredocs (quoted bodies are data, unquoted bodies are
scanned for substitutions) and the control operators. It never guesses: an unterminated quote or
nesting deeper than ``MAX_DEPTH`` raises ``ParseError`` and the gate refuses the command.
"""

from __future__ import annotations

import re

from carter.gate.build import build
from carter.gate.quoting import decode_ansi_c
from carter.gate.words import Cmd, Heredoc, ParseError, Word

MAX_DEPTH = 8
WORD_END = " \t\n;&|()<>"
REDIR = re.compile(r"(\d*)(&>>|&>|>>|>\||>&|>|<<<|<<-|<<|<&|<>|<)")
BRACE = re.compile(r"\{[^\s{}]*(?:,|\.\.)[^\s{}]*\}")
GLOB_SET = re.compile(r"\[[^\s\]]+\]")
PARAM = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9?$!@*#-]")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
Token = tuple  # ("w", Word) | ("op", str) | ("nl",) | ("redir", str) | ...


class Lexer:
    def __init__(self, src: str, home: str) -> None:
        self.src, self.n, self.home = src, len(src), home

    # ---- token stream ------------------------------------------------------------------------
    def lex(self, i: int, closer: str | None, depth: int) -> tuple[list[Token], int]:
        if depth > MAX_DEPTH:
            raise ParseError("nesting too deep")
        src, paren = self.src, 0
        toks: list[Token] = []
        pending: list[Heredoc] = []
        while i < self.n:
            c = src[i]
            if c in " \t":
                i += 1
            elif c == "\\" and src[i + 1 : i + 2] == "\n":
                i += 2
            elif c == "#":
                i = src.find("\n", i)
                i = self.n if i < 0 else i
            elif c == "\n":
                toks.append(("nl",))
                i = self.read_heredocs(i + 1, pending)
            elif c == ")" and closer == ")" and paren == 0:
                return toks, i + 1
            elif c in "<>" and src[i + 1 : i + 2] == "(":
                word, i = self.scan_word(i, depth)
                toks.append(("w", word))
            else:
                op, size = self.operator(i)
                if op in ("(", ")"):
                    paren += 1 if op == "(" else -1
                    paren = max(paren, 0)
                if op is not None:
                    toks.append(("op", op))
                    i += size
                elif m := REDIR.match(src, i):
                    i = self.redirection(m, i, toks, pending, depth)
                else:
                    word, i = self.scan_word(i, depth)
                    toks.append(("w", word))
        if closer is not None:
            raise ParseError("unterminated substitution")
        self.read_heredocs(self.n, pending)
        return toks, i

    def operator(self, i: int) -> tuple[str | None, int]:
        s = self.src
        if s.startswith("&>", i):
            return None, 0  # a redirection, handled by REDIR
        for op in (";;&", ";;", ";&", "&&", "||", "|&"):
            if s.startswith(op, i):
                return op, len(op)
        if s[i] in ";&|()":
            return s[i], 1
        return None, 0

    def redirection(
        self, m: re.Match[str], i: int, toks: list[Token], pending: list[Heredoc], depth: int
    ) -> int:
        op = m.group(2)
        j = m.end()
        while j < self.n and self.src[j] in " \t":
            j += 1
        if j >= self.n or self.src[j] in "\n;&|()":
            raise ParseError("redirection without a target")
        target, j = self.scan_word(j, depth)
        if op in ("<<", "<<-"):
            hd = Heredoc(delim=target.text, quoted=target.quoted, strip_tabs=op == "<<-")
            pending.append(hd)
            toks.append(("heredoc", hd))
        elif op == "<<<":
            hd = Heredoc(delim="", quoted=True, body=target.text, here_string=True)
            hd.subs = list(target.subs)
            toks.append(("heredoc", hd))
        else:
            toks.append(("redir", op))
            toks.append(("w", target))
        return j

    def read_heredocs(self, i: int, pending: list[Heredoc]) -> int:
        for hd in pending:
            lines: list[str] = []
            while i < self.n:
                end = self.src.find("\n", i)
                end = self.n if end < 0 else end
                line = self.src[i:end]
                i = min(end + 1, self.n)
                if (line.lstrip("\t") if hd.strip_tabs else line) == hd.delim:
                    break
                lines.append(line.lstrip("\t") if hd.strip_tabs else line)
            hd.body = "\n".join(lines) + ("\n" if lines else "")
            if not hd.quoted:
                hd.subs = self.text_subs(hd.body, 1)
        pending.clear()
        return i

    # ---- words -------------------------------------------------------------------------------
    def scan_word(self, i: int, depth: int) -> tuple[Word, int]:
        src, w = self.src, Word()
        text: list[str] = []
        start = i
        while i < self.n:
            c = src[i]
            if c in WORD_END:
                if c in "<>" and src[i + 1 : i + 2] == "(":
                    i = self.process_subst(i, w, text, depth)
                    continue
                break
            if c == "'":
                j = src.find("'", i + 1)
                if j < 0:
                    raise ParseError("unterminated single quote")
                text.append(src[i + 1 : j])
                w.quoted, i = True, j + 1
            elif c == '"':
                i = self.double_quoted(i + 1, w, text, depth)
            elif c == "\\":
                if src[i + 1 : i + 2] == "\n":
                    i += 2
                elif i + 1 < self.n:
                    text.append(src[i + 1])
                    w.quoted, i = True, i + 2
                else:
                    text.append("\\")
                    i += 1
            elif c == "$":
                i = self.dollar(i, w, text, depth, in_dq=False)
            elif c == "`":
                i = self.backtick(i, w, text, depth)
            elif c == "~" and not text and not w.quoted:
                i = self.tilde(i, w, text)
            else:
                if c in "*?" or (c == "[" and GLOB_SET.match(src, i)):
                    w.glob = True
                elif c == "{" and self.braces(i):
                    w.brace = True
                elif c == "=" and w.assign is None and not w.quoted and not w.dynamic:
                    name = "".join(text)
                    bare = name[:-1] if name.endswith("+") else name
                    if IDENT.match(bare):
                        w.assign, w.value_at = bare, len(name) + 1
                text.append(c)
                i += 1
        w.text = "".join(text)
        if w.assign is not None and w.value_at > len(w.text):
            w.value_at = len(w.text)
        if i == start:
            raise ParseError("empty word")
        return w, i

    def braces(self, i: int) -> bool:
        return BRACE.match(self.src, i) is not None

    def tilde(self, i: int, w: Word, text: list[str]) -> int:
        j = i + 1
        while j < self.n and self.src[j] not in WORD_END and self.src[j] != "/":
            j += 1
        user = self.src[i + 1 : j]
        if user == "":
            text.append(self.home)
        else:
            w.dynamic = True  # ~user, ~+, ~-
            text.append(self.src[i:j])
        return j

    def double_quoted(self, i: int, w: Word, text: list[str], depth: int) -> int:
        src, w.quoted = self.src, True
        while i < self.n:
            c = src[i]
            if c == '"':
                return i + 1
            if c == "\\" and i + 1 < self.n:
                nxt = src[i + 1]
                if nxt == "\n":
                    i += 2
                    continue
                text.append(nxt if nxt in '$`"\\' else "\\" + nxt)
                i += 2
            elif c == "$":
                i = self.dollar(i, w, text, depth, in_dq=True)
            elif c == "`":
                i = self.backtick(i, w, text, depth)
            else:
                text.append(c)
                i += 1
        raise ParseError("unterminated double quote")

    def dollar(self, i: int, w: Word, text: list[str], depth: int, *, in_dq: bool) -> int:
        src, nxt = self.src, self.src[i + 1 : i + 2]
        if nxt == "(":
            toks, j = self.lex(i + 2, ")", depth + 1)
            w.subs += build(toks)
            w.dynamic = True
            text.append(src[i:j])
            return j
        if nxt == "{":
            j = self.matching_brace(i + 1)
            inner = src[i + 2 : j]
            w.subs += self.text_subs(inner, depth + 1)
            if inner == "HOME":
                text.append(self.home)
            else:
                w.dynamic = True
                text.append(src[i : j + 1])
            return j + 1
        if nxt == "'" and not in_dq:
            return self.ansi_c(i + 2, w, text)
        if nxt == '"' and not in_dq:
            return self.double_quoted(i + 2, w, text, depth)
        m = PARAM.match(src, i + 1)
        if m is None:
            text.append("$")
            return i + 1
        if m.group() == "HOME":
            text.append(self.home)
        else:
            w.dynamic = True
            text.append(src[i : m.end()])
        return m.end()

    def matching_brace(self, i: int) -> int:
        depth = 0
        for j in range(i, self.n):
            c = self.src[j]
            depth += c == "{"
            depth -= c == "}"
            if depth == 0:
                return j
        raise ParseError("unterminated ${")

    def ansi_c(self, i: int, w: Word, text: list[str]) -> int:
        w.quoted = True
        decoded, end = decode_ansi_c(self.src, i)
        text.append(decoded)
        return end

    def backtick(self, i: int, w: Word, text: list[str], depth: int) -> int:
        j, raw = i + 1, []
        while j < self.n and self.src[j] != "`":
            if self.src[j] == "\\" and j + 1 < self.n and self.src[j + 1] in "`\\$":
                j += 1
            raw.append(self.src[j])
            j += 1
        if j >= self.n:
            raise ParseError("unterminated backtick")
        inner = Lexer("".join(raw), self.home)
        toks, _ = inner.lex(0, None, depth + 1)
        w.subs += build(toks)
        w.dynamic = True
        text.append(self.src[i : j + 1])
        return j + 1

    def process_subst(self, i: int, w: Word, text: list[str], depth: int) -> int:
        toks, j = self.lex(i + 2, ")", depth + 1)
        w.subs += build(toks)
        w.dynamic = True
        text.append(self.src[i:j])
        return j

    def text_subs(self, body: str, depth: int) -> list[Cmd]:
        """Commands run by the substitutions inside an expanding text (unquoted heredoc, ${...})."""
        found: list[Cmd] = []
        i, n = 0, len(body)
        inner = Lexer(body, self.home)
        while i < n:
            c = body[i]
            if c == "\\":
                i += 2
            elif c == "$" and body[i + 1 : i + 2] == "(":
                toks, i = inner.lex(i + 2, ")", depth + 1)
                found += build(toks)
            elif c == "`":
                j = i + 1
                while j < n and body[j] != "`":
                    j += 2 if body[j] == "\\" else 1
                if j >= n:
                    raise ParseError("unterminated backtick")
                toks, _ = Lexer(body[i + 1 : j].replace("\\`", "`"), self.home).lex(
                    0, None, depth + 1
                )
                found += build(toks)
                i = j + 1
            else:
                i += 1
        return found


def parse(src: str, home: str) -> list[Cmd]:
    """Parse a command line into simple commands; raises ``ParseError`` when it cannot."""
    toks, _ = Lexer(src, home).lex(0, None, 0)
    return build(toks)
