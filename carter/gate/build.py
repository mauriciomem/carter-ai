"""Group lexer tokens into simple commands (reserved words and control operators separate them)."""

from __future__ import annotations

from carter.gate.words import Cmd, Word

RESERVED = frozenset(
    {
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "while",
        "until",
        "do",
        "done",
        "!",
        "{",
        "}",
        "esac",
        "function",
        "coproc",
    }
)
HEADS = frozenset({"for", "select", "case"})


def build(tokens: list[tuple]) -> list[Cmd]:
    """Group tokens into simple commands (reserved words and control operators separate them)."""
    cmds: list[Cmd] = []
    cur = Cmd()
    pipe = False

    def flush() -> None:
        nonlocal cur, pipe
        if cur.assigns or cur.words or cur.redirs or cur.heredocs:
            cur.pipe_in = pipe
            if cur.discard:
                cur.words = []
            cmds.append(cur)
        cur, pipe = Cmd(), False

    skip_name = ""  # after `function` / `coproc`: the next word may be a NAME, not a command
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        kind = tok[0]
        if kind == "op":
            was_pipe = tok[1] in ("|", "|&")
            flush()
            pipe = was_pipe
        elif kind == "nl":
            flush()
        elif kind == "redir":
            cur.redirs.append((tok[1], tokens[i + 1][1]))
            i += 1
        elif kind == "heredoc":
            cur.heredocs.append(tok[1])
        else:
            word: Word = tok[1]
            if skip_name and not cur.words:
                keyword, skip_name = skip_name, ""
                if keyword == "function" or nxt_is_brace(tokens, i):
                    i += 1  # NAME of a function / named coprocess: not a command
                    continue
            if not cur.words and not cur.discard:
                if word.assign is not None:
                    cur.assigns.append(word)
                elif not word.quoted and word.text in RESERVED:
                    skip_name = word.text if word.text in ("function", "coproc") else ""
                elif not word.quoted and word.text in HEADS:
                    cur.discard = True
                    cur.words.append(word)
                else:
                    cur.words.append(word)
            else:
                cur.words.append(word)
        i += 1
    flush()
    return cmds


def nxt_is_brace(tokens: list[tuple], i: int) -> bool:
    """True when the token after ``tokens[i]`` is the word ``{``: then ``tokens[i]`` is a name."""
    after = tokens[i + 1] if i + 1 < len(tokens) else None
    return after is not None and after[0] == "w" and after[1].text == "{" and not after[1].quoted
