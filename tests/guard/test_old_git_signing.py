"""The minimum git for signing, on the git of this machine (CI ``git-old``: git 2.39).

``key::`` literals reach ``ssh-keygen`` only through ``-U`` (git >= 2.40), so T2 refuses older git
(``E-GIT-OLD``, 2.40 text) and ``identity add`` writes nothing. On git 2.39 these tests prove the
refusal for real; on newer git they prove the check passes.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from carter.identity import shim
from carter.identity.errors import E_GIT_OLD, IdentityError

pytestmark = pytest.mark.gitold


def real_git() -> tuple[int, int]:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)", out)
    assert match
    return int(match.group(1)), int(match.group(2))


def test_check_git_matches_the_real_git() -> None:
    version = real_git()
    if version < (2, 40):
        with pytest.raises(IdentityError) as err:
            shim.check_git()
        assert err.value.code == E_GIT_OLD
    else:
        assert shim.check_git() >= (2, 40)


@pytest.mark.skipif(real_git() >= (2, 40), reason="needs a git older than 2.40")
def test_identity_add_writes_nothing_on_git_below_2_40(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import os
    from pathlib import Path

    from carter import identity_add

    home = Path(os.environ["HOME"])
    before = sorted(p.name for p in home.rglob("*"))
    with pytest.raises(IdentityError):
        identity_add.plan_add(identity_add.AddRequest("octocat", "key::ssh-ed25519 AAAA", "/x/k"))
    assert sorted(p.name for p in home.rglob("*")) == before
