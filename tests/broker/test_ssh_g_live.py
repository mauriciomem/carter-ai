# ruff: noqa: E501
"""The ssh of this machine, judged by B's key list (plan 007 step 20; Apple's ``/usr/bin/ssh`` on macOS).

``-F`` points at a throwaway file, so the developer's own ``~/.ssh/config`` is never read (OpenSSH
ignores ``$HOME``, spike C3); ``ssh -G`` only prints the effective configuration and exits.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from carter.aplus import sshcfg

SSH = next((p for p in ("/usr/bin/ssh", "/bin/ssh") if os.path.exists(p)), "")
pytestmark = pytest.mark.skipif(not SSH, reason="OpenSSH is not installed")


def effective(tmp_path: Path, config: str) -> str:
    file = tmp_path / "config"
    file.write_text(config)
    done = subprocess.run(
        [SSH, "-F", str(file), "-G", "git@github.com"],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_a_plain_config_has_nothing_to_flag(tmp_path: Path) -> None:
    out = effective(tmp_path, "Host github.com\n  User git\n")
    assert "hostname github.com" in out and "user git" in out
    assert sshcfg.parse_ssh_g(out) == []


@pytest.mark.parametrize(
    ("config", "key"),
    [
        ("Host github.com\n  ProxyCommand nc %h %p\n", "proxycommand"),
        ("Host github.com\n  PermitLocalCommand yes\n  LocalCommand echo hi\n", "localcommand"),
    ],
)
def test_the_command_options_show_up_in_ssh_g_and_are_flagged(
    tmp_path: Path, config: str, key: str
) -> None:
    assert key in {f.key for f in sshcfg.parse_ssh_g(effective(tmp_path, config))}


def test_match_user_git_only_applies_with_the_push_user(tmp_path: Path) -> None:
    """Erratum T4: `ssh -G github.com` would miss a `Match user git` block; B asks for git@."""
    config = "Match user git\n  ProxyCommand nc %h %p\n"
    flagged = {f.key for f in sshcfg.parse_ssh_g(effective(tmp_path, config))}
    assert "proxycommand" in flagged
    bare = subprocess.run(
        [SSH, "-F", str(tmp_path / "config"), "-G", "github.com"],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert "proxycommand" not in bare.stdout
