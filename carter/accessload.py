"""Read the human's ``[access]`` and keep the one-time upgrade notice.

``[access]`` lives only in the human's ``config.toml`` (each key has one owning file):
nothing here reads the workspace's ``carter.yaml`` (``carter.access.resolve_config`` does)
or the file Carter writes itself. The judging of the table is ``carter.access``'s.

The notice is recorded in ``guard-state.json`` (a Carter-owned file), as the additive key
``access_notice``, and only when it was shown to a human at a terminal: an agent shell or a
pipe never counts, so it cannot silence the notice for the human. A machine with no state
file records nothing (see ``record_notice``).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from carter.access import UNREADABLE, UserAccess
from carter.guard.state import load, save
from carter.identity.config import ConfigError, read_document
from carter.identity.errors import IdentityError
from carter.install.paths import carter_config_path, guard_state_path
from carter.terminal import is_agent_shell

# TODO: point to `carter access --help` once that command exists.
NOTICE = "! access level is now strict (see: carter update --help)"
_KEY = "access_notice"


def load_user_access(base_dir: Path | None = None) -> UserAccess:
    """The ``[access]`` table of ``config.toml``; a file that cannot be parsed fails closed."""
    try:
        doc = read_document(carter_config_path(base_dir))
    except ConfigError:
        return UserAccess(error=UNREADABLE)
    return UserAccess(table=(doc or {}).get("access"))


def notice_due(base_dir: Path | None = None, user: UserAccess | None = None) -> bool:
    """True while ``[access]`` is absent and no human has been shown the notice yet.

    ``user`` is what ``load_user_access`` already returned, to read the file once."""
    user = user or load_user_access(base_dir)
    if user.table is not None or user.error:
        return False  # the human set a level (or it is broken: the fallback line says so)
    try:
        return _KEY not in load(guard_state_path(base_dir)).extra
    except IdentityError:
        return True  # a corrupt state file cannot record anything: keep telling


def _human_at_terminal() -> bool:
    return not is_agent_shell() and sys.stdin.isatty() and sys.stdout.isatty()


def record_notice(base_dir: Path | None = None, *, today: str | None = None) -> bool:
    """Remember the notice as shown, if a human at a terminal saw it. True when recorded.

    Only an existing ``guard-state.json`` is updated: creating one would turn "no guards
    installed" (which ``check --host`` and ``guard status`` report) into "state present".
    Without it the notice simply keeps showing."""
    path = guard_state_path(base_dir)
    if not path.exists() or not _human_at_terminal():
        return False
    try:
        state = load(path)
        state.extra[_KEY] = {"date": today or date.today().isoformat(), "level": "strict"}
        save(state, path)
    except (IdentityError, OSError):
        return False
    return True
