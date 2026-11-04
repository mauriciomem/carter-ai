"""The optional ``git ai-commit`` alias (consent group ``alias``; plan 005 step 19, freeze H15).

``alias.ai-commit`` is single-valued, so Carter sets it (in ``~/.carter/gitconfig``) only if the
user has none; theirs wins and the chain snippet is printed. The value has **no** ``"$@"``: git
appends the alias's arguments itself, and a second copy would duplicate them (spike B 8, R1). The
``cd`` makes the command run from where the user typed it (git runs aliases at the top level).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from carter.guard import gitconfig

ALIAS_KEY = "alias.ai-commit"
ALIAS_VALUE = '!cd "${GIT_PREFIX:-.}" && carter commit'


@dataclass
class AliasPlan:
    status: Literal["set", "ours", "kept-user-value"]
    snippet: str = ""


def plan_alias(global_config: Path) -> AliasPlan:
    """Ours only if the user has no ``alias.ai-commit`` (includes followed). Carter's own value,
    read back through the include, counts as ours, not as the user's."""
    have = gitconfig._file_git(str(global_config), "--includes", "--get", ALIAS_KEY)
    if have.returncode != 0:
        return AliasPlan("set")
    if have.stdout.rstrip("\n") == ALIAS_VALUE:
        return AliasPlan("ours")
    snippet = (
        f"{ALIAS_KEY} is already set in your git config; Carter kept it. To use Carter's too, "
        f"run `carter commit` directly or chain: {ALIAS_KEY} = {ALIAS_VALUE}"
    )
    return AliasPlan("kept-user-value", snippet)
