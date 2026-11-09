"""There is no user-config way to redirect the broker's home (maestro decision, .

the broker's child ``HOME`` and the ``~/.ssh/config`` scan come from the system account entry. A
``[broker] home`` in ``config.toml`` is one more place to plant a hostile ssh config, so the key
does not exist: it is reported as unknown and nothing reads it.
"""

from __future__ import annotations

import os
import pwd
from pathlib import Path

import pytest

from carter.broker import checks, env
from carter.identity.config import load_identity
from carter.identity.schema import schema_names
from carter.install.paths import carter_config_path

PASSWD_HOME = Path(pwd.getpwuid(os.geteuid()).pw_dir)


def write(text: str) -> Path:
    path = carter_config_path(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"schema = 2\n{text}")
    return path


def test_the_schema_has_no_home_key_for_broker() -> None:
    assert "home" not in schema_names()["broker"]


def test_a_broker_home_in_config_is_an_unknown_key() -> None:
    evil = Path(os.environ["HOME"]) / "evil-home"
    write(f'[broker]\nhome = "{evil}"\n')
    cfg = load_identity()
    assert "broker.home" in cfg.unknown_keys
    assert not hasattr(cfg.broker, "home")


def test_a_broker_home_in_config_has_no_effect_on_the_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evil = tmp_path / "evil-home"
    (evil / ".ssh").mkdir(parents=True)
    (evil / ".ssh" / "config").write_text('Match exec "touch /tmp/never"\n')
    monkeypatch.setenv("HOME", str(tmp_path / "other"))  # nor does $HOME
    write(f'[broker]\nhome = "{evil}"\nmin_dwell_ms = 900\n')
    ctx = checks.load_context(git="/usr/bin/git", gh="")
    assert ctx.home == PASSWD_HOME and ctx.home != evil
    assert ctx.cfg.broker.min_dwell_ms == 900  # the known key in the same table still works
    assert env.account_home() == PASSWD_HOME


def test_the_writer_refuses_to_rewrite_a_file_with_the_unknown_key() -> None:
    from carter.identity.schema import IdentityConfig
    from carter.identity.writer import UnmodelledKeysError, write_config

    path = write('[broker]\nhome = "/x"\n')
    with pytest.raises(UnmodelledKeysError):
        write_config(IdentityConfig(), path)
