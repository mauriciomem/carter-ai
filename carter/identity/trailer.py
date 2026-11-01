"""The attribution trailer for a resolved identity (RFC-0007 §4.1 tiers). Pure.

T0 credits Carter without an email; T1 credits the LLM account by its noreply address.
In slice 1 T2 uses the same co-author trailer (nothing is signed yet; that is slice 2b).
A refused resolution has no trailer: Carter does not attribute commits it will not make.
"""

from __future__ import annotations

from carter.identity.resolve import Resolution
from carter.identity.schema import IdentityConfig

ASSISTED_BY_CARTER = "Assisted-by: Carter"


def noreply_email(cfg: IdentityConfig) -> str:
    """The configured email, or the one derived from login and id."""
    ident = cfg.identity
    return ident.email or f"{ident.id}+{ident.login}@users.noreply.github.com"


def coauthor_trailer(cfg: IdentityConfig, res: Resolution) -> str:
    """``Assisted-by: Carter`` at T0, ``Co-authored-by: <login> <noreply>`` at T1/T2,
    ``""`` when the resolution refuses commits."""
    if res.commits == "refused":
        return ""
    if res.tier == "t0":
        return ASSISTED_BY_CARTER
    return f"Co-authored-by: {cfg.identity.login} <{noreply_email(cfg)}>"
