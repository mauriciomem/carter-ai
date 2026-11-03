"""What the A+ checks return: findings that name a place, never a value.

``Finding`` is shared by the repo-config, SSH-config and signature checks. ``scope`` is a
git config scope (``system|global|local|worktree|command``) or ``hooks`` / ``ssh config`` /
``commit``; ``key`` is a config key, a hook event, an ssh option or a commit sha; ``origin``
is the file it came from. Values (a credential helper's command line, a URL's userinfo) are
never stored, so a finding is safe to print and to put in an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from carter.identity.errors import E_B_REPOCFG, E_B_UNSIGNED, IdentityError, registry

_USERINFO = re.compile(r"(://)[^/@\s]*@")


def mask_userinfo(text: str) -> str:
    """``https://user:secret@host`` → ``https://***@host`` (keys can embed URLs)."""
    return _USERINFO.sub(r"\1***@", text)


@dataclass(frozen=True, order=True)
class Finding:
    code: str
    scope: str
    key: str
    origin: str = ""
    reason: str = ""

    def render(self) -> str:
        where = f" ({self.origin})" if self.origin else ""
        why = f": {self.reason}" if self.reason else ""
        return f"{self.scope} {self.key}{where}{why}"


def to_error(findings: list[Finding]) -> IdentityError | None:
    """The registry error for the first finding (``None`` if there are none)."""
    if not findings:
        return None
    first = findings[0]
    message = registry()[first.code].message
    detail = "; ".join(f.render() for f in findings)
    if first.code == E_B_REPOCFG:
        message = message.replace("`<scope>`", f"`{first.scope}`").replace(
            "`<key>`", f"`{first.key}`"
        )
    elif first.code == E_B_UNSIGNED:
        shas = ", ".join(f.key[:12] for f in findings)
        message = message.replace("`<shas>`", f"`{shas}`")
    return IdentityError(first.code, message, detail=detail)
