"""`[access]` in ~/.carter/config.toml is a known table: read, kept on every write, never unknown.

The table has free keys (capability ids), so the reader keeps the scalars as written and the
access resolver judges them. A real config holds exactly `[access] level = "guarded"`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carter import unknownkeys
from carter.identity import load_identity
from carter.identity.schema import Identity, IdentityConfig
from carter.identity.writer import write_managed
from config_files import dumps

GUARDED = 'schema = 2\n\n[access]\nlevel = "guarded"\n'


def _file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_users_real_table_is_known(tmp_path):
    path = _file(tmp_path, GUARDED)
    cfg = load_identity(path)
    assert cfg.access == (("level", "guarded"),)
    assert cfg.unknown_keys == ()
    assert unknownkeys.config_toml(path) == []


def test_a_table_without_schema_line_is_known_too(tmp_path):
    assert load_identity(_file(tmp_path, '[access]\nlevel = "guarded"\n')).unknown_keys == ()


def test_absent_table_is_empty(tmp_path):
    assert load_identity(_file(tmp_path, "schema = 2\n")).access == ()


def test_wrong_values_are_kept_for_the_resolver_to_report(tmp_path):
    cfg = load_identity(_file(tmp_path, "[access]\npr_write = 1\nflag = true\ngitcommit = 'x'\n"))
    assert cfg.access == (("pr_write", 1), ("flag", True), ("gitcommit", "x"))
    assert cfg.unknown_keys == ()


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("[access]\nlevel = ['a']\n", ("access.level",)),
        ("[access.nested]\nx = 1\n", ("access.nested",)),
        ("[access]\nratio = 1.5\n", ("access.ratio",)),
        ("access = 'guarded'\n", ("access",)),
    ],
)
def test_what_cannot_be_written_back_is_unknown(tmp_path, text, names):
    assert load_identity(_file(tmp_path, text)).unknown_keys == names


def test_dumps_round_trips_the_table_in_file_order(tmp_path):
    cfg = load_identity(_file(tmp_path, '[access]\npr_write = "ask"\nlevel = "relaxed"\n'))
    text = dumps(cfg)
    assert '[access]\npr_write = "ask"\nlevel = "relaxed"\n' in text
    assert load_identity(_file(tmp_path, text)).access == cfg.access


def test_an_odd_key_is_quoted(tmp_path):
    cfg = IdentityConfig(state="current", access=(("a b", "x"),))
    assert '"a b" = "x"' in dumps(cfg)


def test_a_carter_write_leaves_the_table_and_the_file_alone(tmp_path):
    """Carter writes the managed file only: `[access]` and `config.toml` stay byte for byte."""
    path = _file(tmp_path, GUARDED)
    before = path.read_bytes()
    fresh = IdentityConfig(state="current", identity=Identity(login="bot"))
    assert write_managed(fresh, path) is True
    again = load_identity(path)
    assert again.access == (("level", "guarded"),)
    assert again.identity.login == "bot"
    assert path.read_bytes() == before
