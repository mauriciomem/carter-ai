"""The role-b lines shared by ``carter identity show|add`` and ``carter check --host``
(plan 006 steps 8 and 11; freeze K7, K11, K12).

In role ``author`` the human is credited by one ``Co-authored-by`` line built from their own git
config, so three things matter: is that identity usable, does GitHub know the address (it is the
human's only credit), and is this repository one that checks a DCO sign-off against the author.
Names and states only: the human's name and email are never printed (the output of ``check
--host`` can land in an agent transcript).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from carter.checkitems import Item
from carter.identity import coauthor, github
from carter.identity.errors import E_HUMAN_IDENTITY
from carter.identity.schema import IdentityConfig
from carter.identity.trailer import noreply_email

DCO_FILES = (".github/dco.yml", ".github/dco.yaml", ".dco.yml", "DCO")
USE_NOREPLY = "or set user.email to your <id>+<login>@users.noreply.github.com address."


def dco_file(cwd: Path) -> str:
    """The first DCO configuration file found from ``cwd`` up to the repository root, else ``""``.
    Only the file name is returned."""
    here = cwd.resolve()
    for folder in (here, *here.parents):
        for name in DCO_FILES:
            if (folder / name).is_file():
                return name
        if (folder / ".git").exists():
            break
    return ""


def human_items(
    cfg: IdentityConfig,
    cwd: Path,
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    refresh: bool = False,
    record: bool = True,
) -> list[Item]:
    """Items for role ``author``. ``refresh`` asks GitHub and ``gh`` (a human terminal only:
    ``refresh_link`` itself refuses in an agent shell) and fills the cache; otherwise the cache
    is read and nothing leaves the machine."""
    env = os.environ if env is None else env
    human = coauthor.human_identity(cwd, noreply_email(cfg), env)
    if not human.ok:
        return [
            Item(
                "red",
                "human identity",
                f"{E_HUMAN_IDENTITY}: your git identity in this directory is unusable "
                f"({human.problem}); role author refuses to commit",
                "Set user.name and user.email in your git config (an includeIf override counts).",
            )
        ]
    out = [Item("ok", "human identity", "your git user.name and user.email are usable")]
    if refresh:
        state = coauthor.refresh_link(
            human.email,
            lambda login: github.get_user(login, env),
            coauthor.gh_user_emails,
            env,
            home,
            record=record,
        )
    else:
        state = coauthor.cached_link(human.email, home)
    if state:
        text = f"your address is linked to a GitHub account ({state})"
        out.append(Item("ok", "co-author link", text))
    else:
        out.append(
            Item(
                "warn",
                "co-author link",
                "your address is not known to be linked to a GitHub account: in role b the "
                "Co-authored-by line is your only credit there",
                "Run `carter check --host` in your own terminal to check it, " + USE_NOREPLY,
            )
        )
    return out


def dco_items(cwd: Path) -> list[Item]:
    name = dco_file(cwd)
    if not name:
        return []
    return [
        Item(
            "warn",
            "dco",
            f"this repository has {name}: a DCO check compares the sign-off with the AUTHOR, and "
            "Carter never signs off for the LLM, so role author cannot pass it",
            "Pin `role: co-author` in carter.yaml and run `carter update` for this workspace.",
        )
    ]
