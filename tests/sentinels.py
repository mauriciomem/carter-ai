"""Token-shaped test values, built at runtime.

GitHub push protection and secret scanning flag a source file that holds a contiguous
``github_pat_`` / ``ghp_`` (and friends) followed by 20 or more token characters, even when
the value is obviously fake. Every such sentinel in the tests is assembled here instead, so
no file in the repository contains one (``tests/test_no_token_literals.py`` enforces it).
The values are made up and never valid credentials.
"""

from __future__ import annotations

_FILLER = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH"


def fine_grained(tag: str = "SENTINEL") -> str:
    """A fake fine-grained PAT that passes ``ghtoken.validate_token``; ``tag`` is greppable."""
    return "github_pat_" + "11AAAAAAA0" + tag + "_" + _FILLER


def prefixed(prefix: str, tag: str = "SENTINEL") -> str:
    """A fake classic/app token such as ``ghp_`` + 36 characters containing ``tag``."""
    assert prefix in {"ghp_", "gho_", "ghu_", "ghs_", "ghr_"}
    return prefix + (tag + _FILLER)[:36]


def passphrase(tag: str = "SENTINEL") -> str:
    """A fake key passphrase made of random hex at call time, greppable through ``tag``.

    Tests type it into a PTY and then assert it appears in no argv, env, log, exception or return
    value. It is never a literal in the source, so it cannot be mistaken for a real secret."""
    import secrets

    return f"pw-{tag}-{secrets.token_hex(6)}"
