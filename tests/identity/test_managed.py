"""The managed file as the reader sees it: ownership, merge rules, fail-closed checks."""

from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from carter import ui
from carter.identity import load_identity
from carter.identity.managed import (
    MANAGED_NAME,
    OWNED,
    PIN_KEYS,
    UNREADABLE,
    UNSAFE,
)
from carter.identity.schema import SECTIONS, IdentityConfig, Workspace


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def put_managed(cfg_path: Path, text: str, mode: int = 0o600) -> Path:
    target = cfg_path.with_name(MANAGED_NAME)
    target.write_text(text)
    target.chmod(mode)
    return target


def sample(f: Any) -> Any:
    """A value for field ``f`` that differs from its default and is legal."""
    choices = f.metadata.get("choices")
    if choices:
        return next((c for c in choices if c != f.default), None)
    if isinstance(f.default, bool):
        return True
    if isinstance(f.default, int):
        return f.default + 7
    if isinstance(f.default, tuple):
        return ("k1", "k2")
    return "x"


def toml_line(key: str, value: Any) -> str:
    if isinstance(value, tuple):
        return f"{key} = [{', '.join(repr(v) for v in value)}]"
    return f"{key} = {str(value).lower() if isinstance(value, bool) else repr(value)}"


def table_text(path: tuple[str, ...], key: str, value: Any) -> str:
    return f"[{'.'.join(path)}]\n{toml_line(key, value)}\n"


ALL = [
    (attr, path, f) for attr, path, cls in SECTIONS for f in fields(cls) if sample(f) is not None
]
IDS = [f"{'.'.join(path)}.{f.name}" for _a, path, f in ALL]


def test_the_ownership_table_names_real_keys():
    schema = {path: {f.name for f in fields(cls)} for _a, path, cls in SECTIONS}
    for path, keys in OWNED.items():
        assert path in schema and set(keys) <= schema[path], path
    assert set(PIN_KEYS) <= {f.name for f in fields(Workspace)}


@pytest.mark.parametrize(("attr", "path", "f"), ALL, ids=IDS)
def test_every_key_has_one_owning_file_both_directions(cfg_path, attr, path, f):
    """Human keys are read from config.toml and ignored in the managed file; derived keys are
    read from the managed file (and, for an older install, from config.toml too)."""
    value = sample(f)
    text = table_text(path, f.name, value)
    expected = value if not isinstance(value, tuple) else tuple(value)
    owned_here = f.name in OWNED.get(path, ())

    cfg_path.write_text(text)  # in config.toml: always read
    assert getattr(getattr(load_identity(cfg_path), attr), f.name) == expected
    cfg_path.unlink()

    put_managed(cfg_path, text)  # in the managed file: read only if Carter owns it
    cfg = load_identity(cfg_path)
    got = getattr(getattr(cfg, attr), f.name)
    if owned_here:
        assert got == expected and not cfg.notes
    else:
        assert got == f.default
        assert len(cfg.notes) == 1 and "not Carter's" in cfg.notes[0]


def test_a_pin_is_read_from_the_managed_file(cfg_path):
    put_managed(cfg_path, '[pins."/w"]\nrole = "author"\nrequire_tier = "t2"\n')
    assert load_identity(cfg_path).workspaces["/w"] == Workspace(role="author", require_tier="t2")


def test_a_human_workspace_key_in_the_managed_file_is_ignored(cfg_path):
    put_managed(
        cfg_path, '[workspaces."/w"]\nmax_tier = "t1"\nallow_project_opencode_edit = true\n'
    )
    cfg = load_identity(cfg_path)
    assert cfg.workspaces == {} and len(cfg.notes) == 1
    put_managed(cfg_path, '[pins."/w"]\nmax_tier = "t1"\nrole = "author"\n')
    cfg = load_identity(cfg_path)
    assert cfg.workspaces["/w"] == Workspace(role="author") and len(cfg.notes) == 1


def test_access_in_the_managed_file_cannot_loosen_anything(cfg_path):
    cfg_path.write_text('[access]\nlevel = "strict"\n')
    put_managed(cfg_path, '[access]\nlevel = "relaxed"\n')
    cfg = load_identity(cfg_path)
    assert cfg.access == (("level", "strict"),)


def test_a_table_in_both_files_goes_to_config_toml_and_says_so(cfg_path):
    cfg_path.write_text('[identity]\nlogin = "mine"\n')
    put_managed(
        cfg_path, '[identity]\nlogin = "theirs"\nid = 5\n[github]\nread_token_file = "/t"\n'
    )
    cfg = load_identity(cfg_path)
    assert cfg.identity.login == "mine" and cfg.identity.id == 0
    assert cfg.github.read_token_file == "/t"  # a table only the managed file sets
    assert cfg.notes == ("config.toml wins over config-managed.toml: identity",)


def test_a_pin_in_both_goes_to_config_toml(cfg_path):
    cfg_path.write_text('[workspaces."/w"]\nrole = "co-author"\n')
    put_managed(cfg_path, '[pins."/w"]\nrole = "author"\n')
    cfg = load_identity(cfg_path)
    assert cfg.workspaces["/w"].role == "co-author" and len(cfg.notes) == 1


def test_an_older_install_keeps_loading(cfg_path):
    cfg_path.write_text(
        '[access]\nlevel = "guarded"\n[attribution]\nfooter = "f"\n'
        '[identity]\nlogin = "bot"\nid = 3\n[identity.signing]\nfingerprint = "SHA256:a"\n'
    )
    cfg = load_identity(cfg_path)
    assert (cfg.identity.login, cfg.signing.fingerprint, cfg.access) == (
        "bot",
        "SHA256:a",
        (("level", "guarded"),),
    )
    assert cfg.notes == () and cfg.unknown_keys == ()


class TestFailClosed:
    GOOD = '[identity]\nlogin = "bot"\nid = 3\n'

    def test_a_good_file_loads(self, cfg_path):
        put_managed(cfg_path, self.GOOD)
        cfg = load_identity(cfg_path)
        assert cfg.identity.login == "bot" and cfg.notes == ()

    def test_a_loose_mode_is_refused(self, cfg_path):
        cfg_path.write_text('[access]\nlevel = "guarded"\n')
        put_managed(cfg_path, self.GOOD, mode=0o644)
        cfg = load_identity(cfg_path)
        assert cfg.identity.login == "" and cfg.notes == (UNSAFE,)
        assert cfg.access == (("level", "guarded"),)  # the human file is unaffected

    @pytest.mark.parametrize("mode", [0o640, 0o604, 0o660, 0o666])
    def test_any_group_or_other_bit_is_refused(self, cfg_path, mode):
        put_managed(cfg_path, self.GOOD, mode=mode)
        assert load_identity(cfg_path).notes == (UNSAFE,)

    def test_a_stricter_mode_is_fine(self, cfg_path):
        put_managed(cfg_path, self.GOOD, mode=0o400)
        assert load_identity(cfg_path).identity.login == "bot"

    def test_a_symlink_at_the_path_is_refused(self, tmp_path, cfg_path):
        real = tmp_path / "real.toml"
        real.write_text(self.GOOD)
        real.chmod(0o600)
        cfg_path.with_name(MANAGED_NAME).symlink_to(real)
        cfg = load_identity(cfg_path)
        assert cfg.identity.login == "" and cfg.notes == (UNSAFE,)

    def test_a_symlink_swap_after_a_good_read_is_refused(self, tmp_path, cfg_path):
        target = put_managed(cfg_path, self.GOOD)
        assert load_identity(cfg_path).identity.login == "bot"
        evil = tmp_path / "evil.toml"
        evil.write_text('[identity]\nlogin = "evil"\n')
        evil.chmod(0o600)
        target.unlink()
        target.symlink_to(evil)
        cfg = load_identity(cfg_path)
        assert cfg.identity.login == "" and cfg.notes == (UNSAFE,)

    def test_a_symlink_in_the_parent_is_refused(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        put_managed(real / "config.toml", self.GOOD)
        link = tmp_path / "link"
        link.symlink_to(real)
        cfg = load_identity(link / "config.toml")
        assert cfg.identity.login == "" and cfg.notes == (UNSAFE,)

    def test_a_file_of_another_owner_is_refused(self, cfg_path, monkeypatch):
        put_managed(cfg_path, self.GOOD)
        monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
        assert load_identity(cfg_path).notes == (UNSAFE,)

    def test_a_directory_is_refused(self, cfg_path):
        cfg_path.with_name(MANAGED_NAME).mkdir()
        assert load_identity(cfg_path).notes in ((UNSAFE,), (UNREADABLE,))

    @pytest.mark.parametrize(
        "text",
        [
            "[identity\nlogin = 1",
            '[identity]\nid = "not a number"\n',
            '[pins."/w"]\nrole = "boss"\n',
        ],
        ids=["syntax", "type", "choice"],
    )
    def test_an_unreadable_file_is_empty_and_says_so(self, cfg_path, text):
        put_managed(cfg_path, text)
        cfg = load_identity(cfg_path)
        assert cfg.identity.login == "" and cfg.workspaces == {} and cfg.notes == (UNREADABLE,)

    def test_a_missing_file_is_not_a_problem(self, cfg_path):
        cfg = load_identity(cfg_path)
        assert cfg == IdentityConfig(state="absent")

    def test_no_derived_identity_is_trusted_when_the_check_fails(self, cfg_path):
        put_managed(
            cfg_path, self.GOOD + '[identity.signing]\npublic_key = "ssh-ed25519 AAA"\n', 0o666
        )
        from carter.identity.resolve import configured_tier

        assert configured_tier(load_identity(cfg_path)) == "t0"


def test_every_note_fits_the_output_budget(cfg_path):
    cfg_path.write_text('[identity]\nlogin = "mine"\n')
    put_managed(
        cfg_path,
        '[identity]\nlogin = "x"\n[access]\nlevel = "relaxed"\n[broker]\nmin_dwell_ms = 9\n',
    )
    notes = [*load_identity(cfg_path).notes, UNSAFE, UNREADABLE]
    assert notes and all(len(n) <= ui.MAX - 8 for n in notes)


class TestANestedEntryNeverLiftsAParentCap:
    """``/repo`` is capped by hand; a pin for ``/repo/sub`` (managed or legacy) must not hide it."""

    def cfg(self, cfg_path, human: str, pins: str = "") -> IdentityConfig:
        cfg_path.write_text(human)
        if pins:
            put_managed(cfg_path, pins)
        return load_identity(cfg_path)

    CAP = '[workspaces."/repo"]\nmax_tier = "t1"\n'

    def test_a_managed_pin_below_a_capped_parent_keeps_the_cap(self, cfg_path):
        cfg = self.cfg(cfg_path, self.CAP, '[pins."/repo/sub"]\nrole = "co-author"\n')
        assert cfg.workspaces["/repo/sub"].max_tier == "t1"
        assert cfg.workspaces["/repo/sub"].role == "co-author"

    def test_a_legacy_pin_in_config_toml_keeps_it_too(self, cfg_path):
        cfg = self.cfg(cfg_path, self.CAP + '[workspaces."/repo/sub"]\nrole = "co-author"\n')
        assert cfg.workspaces["/repo/sub"].max_tier == "t1"

    def test_the_resolved_tier_under_the_nested_workspace_is_capped(self, cfg_path):
        from carter.identity.env import workspace_for
        from carter.identity.resolve import resolve

        cfg = self.cfg(
            cfg_path,
            self.CAP,
            '[identity]\nlogin = "b"\nid = 1\nemail = "1+b@users.noreply.github.com"\n'
            '[pins."/repo/sub"]\nrole = "co-author"\n',
        )
        assert workspace_for(cfg, "/repo/sub") == "/repo/sub"
        assert resolve(cfg, workspace="/repo/sub", env={}).tier == "t1" and cfg.identity.login

    def test_the_strictest_of_every_ancestor_wins_whichever_is_nested(self, cfg_path):
        parent_t0 = (
            '[workspaces."/repo"]\nmax_tier = "t0"\n[workspaces."/repo/sub"]\nmax_tier = "t1"\n'
        )
        parent_t1 = (
            '[workspaces."/repo"]\nmax_tier = "t1"\n[workspaces."/repo/sub"]\nmax_tier = "t0"\n'
        )
        assert self.cfg(cfg_path, parent_t0).workspaces["/repo/sub"].max_tier == "t0"
        assert self.cfg(cfg_path, parent_t1).workspaces["/repo/sub"].max_tier == "t0"
        assert self.cfg(cfg_path, parent_t1).workspaces["/repo"].max_tier == "t1"  # not the child's

    def test_it_reaches_every_depth_and_only_real_children(self, cfg_path):
        cfg = self.cfg(
            cfg_path,
            self.CAP,
            '[pins."/repo/a/b/c"]\nrole = "author"\n[pins."/repo-x"]\nrole = "author"\n'
            '[pins."/other"]\nrole = "author"\n',
        )
        assert cfg.workspaces["/repo/a/b/c"].max_tier == "t1"
        assert cfg.workspaces["/repo-x"].max_tier == "" and cfg.workspaces["/other"].max_tier == ""

    def test_a_pin_cannot_be_written_under_a_cap_that_forbids_it(self, cfg_path):
        from carter.identity.pin import plan_pin

        cfg = self.cfg(cfg_path, self.CAP)
        plan = plan_pin(cfg, "/repo/sub", role="author", require_tier="")
        assert "max_tier t1 caps role author" in plan.refusal

    def test_an_opt_out_is_per_path_and_a_nested_pin_does_not_remove_it(self, cfg_path, tmp_path):
        from carter.guard.optout import active_optouts

        repo = tmp_path / "repo"
        (repo / "sub").mkdir(parents=True)
        cfg = self.cfg(
            cfg_path,
            f'[workspaces."{repo}"]\nallow_project_opencode_edit = true\n',
            f'[pins."{repo}/sub"]\nrole = "co-author"\n',
        )
        assert active_optouts(cfg).workspaces == [str(repo.resolve())]
