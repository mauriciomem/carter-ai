"""Strip the environment variables that can change who a git commit is by.

``scrub_git_env`` is pure: it returns a new dict and never touches ``os.environ``. The
state repo's single git entry point applies it (and later slices reuse it for ``carter
commit``), so a polluted shell or server environment cannot pick the author, the
committer, injected config (``GIT_CONFIG_COUNT``/``KEY_n``/``VALUE_n``,
``GIT_CONFIG_PARAMETERS``) or another repository (``GIT_DIR`` and friends).

``GIT_CONFIG_GLOBAL``, ``GIT_CONFIG_SYSTEM`` and ``GIT_CONFIG_NOSYSTEM`` are kept: they
choose where the human's own git config lives, which is how the human identity is found.
"""

from __future__ import annotations

from collections.abc import Mapping

_KEEP = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"})
_PREFIXES = ("GIT_AUTHOR_", "GIT_COMMITTER_", "GIT_CONFIG_", "CARTER_IDENTITY")
_EXACT = frozenset(
    {"GIT_CONFIG", "EMAIL", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
)


def scrub_git_env(env: Mapping[str, str]) -> dict[str, str]:
    """Copy of ``env`` without author/committer/config/repository overrides."""
    return {
        key: value
        for key, value in env.items()
        if key in _KEEP or not (key in _EXACT or key.startswith(_PREFIXES))
    }
