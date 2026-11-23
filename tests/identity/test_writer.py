"""The managed-file writer: ``config-managed.toml`` only, never ``config.toml``."""

from __future__ import annotations

import ast
import os
import stat
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from carter.identity import load_identity
from carter.identity.config import ConfigError
from carter.identity.managed import HEADER, MANAGED_NAME, OWNED, PIN_KEYS
from carter.identity.schema import Github, Identity, IdentityConfig, Signing, Workspace
from carter.identity.writer import WriterError, owned, write_managed
from config_files import dumps as human_dumps

REPO = Path(__file__).resolve().parents[2]

DERIVED = IdentityConfig(
    identity=Identity(login="llm-bot", id=12345, name="llm-bot", email="12345+llm-bot@x"),
    signing=Signing(
        public_key="ssh-ed25519 AAAAC3Nza",
        fingerprint="SHA256:abc",
        private_key_path="~/.ssh/llm-bot_signing",
        previous_public_keys=("ssh-ed25519 OLD1", "ssh-ed25519 OLD2"),
        agent_socket="/run/agent.sock",
        program="op-ssh-sign",
        mode="agent",
    ),
    github=Github(read_token_file="/home/x/.carter/secrets/gh-read.token"),
    workspaces={"/abs/path": Workspace(role="author", require_tier="t2")},
    state="current",
)
EMPTY = IdentityConfig(state="current")


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def managed(cfg_path: Path) -> Path:
    return cfg_path.with_name(MANAGED_NAME)


def test_the_file_starts_with_the_header_and_is_private(cfg_path):
    assert write_managed(DERIVED, cfg_path) is True
    target = managed(cfg_path)
    assert target.read_text().splitlines()[0] == HEADER
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_what_is_written_is_read_back(cfg_path):
    write_managed(DERIVED, cfg_path)
    again = load_identity(cfg_path)
    assert owned(again) == owned(DERIVED)
    assert again.workspaces["/abs/path"].role == "author"
    assert again.signing.previous_public_keys == DERIVED.signing.previous_public_keys


def test_only_derived_keys_are_stored(cfg_path):
    human = replace(
        DERIVED,
        identity=replace(DERIVED.identity, role="author", mode="review"),
        signing=replace(DERIVED.signing, ttl="4h", ssh_bin_dir="/opt/bin"),
        github=replace(DERIVED.github, probe_repo="o/r"),
        workspaces={
            "/w": Workspace(max_tier="t1", allow_project_opencode_edit=True, role="author")
        },
    )
    write_managed(human, cfg_path)
    doc = tomllib.loads(managed(cfg_path).read_text())
    assert set(doc["identity"]) - {"signing"} == {"login", "id", "name", "email"}
    assert (
        "ttl" not in doc["identity"]["signing"] and "ssh_bin_dir" not in doc["identity"]["signing"]
    )
    assert set(doc["github"]) == {"read_token_file"}
    assert doc["pins"] == {"/w": {"role": "author"}}
    assert "workspaces" not in doc


def test_config_toml_is_never_written_or_created(cfg_path):
    write_managed(DERIVED, cfg_path)
    assert not cfg_path.exists()
    text = '# mine\n[attribution]\nfooter = "x"\n[extra]\nkeep = 1\n[access]\nlevel = "guarded"\n'
    cfg_path.write_text(text)
    stamp = cfg_path.stat().st_mtime_ns
    write_managed(replace(DERIVED, identity=Identity(login="other")), cfg_path)
    write_managed(EMPTY, cfg_path)
    assert cfg_path.read_text() == text and cfg_path.stat().st_mtime_ns == stamp


def test_an_equal_write_changes_nothing(cfg_path):
    write_managed(DERIVED, cfg_path)
    assert write_managed(DERIVED, cfg_path) is False


def test_nothing_derived_removes_the_file(cfg_path):
    write_managed(DERIVED, cfg_path)
    assert write_managed(EMPTY, cfg_path) is True
    assert not managed(cfg_path).exists()
    assert write_managed(EMPTY, cfg_path) is False


def test_a_key_holds_only_in_the_file_that_owns_it(cfg_path):
    """Every owned key is written to the managed file and to no other."""
    write_managed(DERIVED, cfg_path)
    doc = tomllib.loads(managed(cfg_path).read_text())
    for path, keys in OWNED.items():
        node = doc
        for part in path:
            node = node[part]
        assert set(node) - {"signing"} == set(keys)  # DERIVED sets every owned key
    assert set(PIN_KEYS) == set(doc["pins"]["/abs/path"])


def test_the_write_is_atomic_a_failed_replace_leaves_the_old_file(cfg_path, monkeypatch):
    write_managed(DERIVED, cfg_path)
    before = managed(cfg_path).read_bytes()

    def boom(*_a, **_k):
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_managed(replace(DERIVED, identity=Identity(login="new")), cfg_path)
    assert managed(cfg_path).read_bytes() == before
    assert sorted(p.name for p in cfg_path.parent.iterdir()) == [MANAGED_NAME]  # no temp file


def test_the_temp_file_is_synced_before_the_rename(cfg_path, monkeypatch):
    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(
        os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1]
    )
    write_managed(DERIVED, cfg_path)
    assert order == ["fsync", "replace"]


def test_a_symlink_at_the_path_is_refused(tmp_path, cfg_path):
    other = tmp_path / "elsewhere"
    other.write_text("keep")
    managed(cfg_path).symlink_to(other)
    with pytest.raises(WriterError, match="symlink"):
        write_managed(DERIVED, cfg_path)
    assert other.read_text() == "keep"


def test_a_symlink_in_the_parent_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(WriterError, match="symlink"):
        write_managed(DERIVED, link / "config.toml")
    assert list(real.iterdir()) == []


def test_a_broken_config_toml_stops_the_write(cfg_path):
    cfg_path.write_text("schema = 2\nbroken [[[")
    with pytest.raises(ConfigError):
        write_managed(DERIVED, cfg_path)
    assert not managed(cfg_path).exists()


class TestConfigTomlHoldsDerivedValues:
    """An older install keeps derived values in config.toml: they win, and a change is
    refused rather than silently shadowed."""

    def legacy(self, cfg_path: Path) -> IdentityConfig:
        cfg_path.write_text(human_dumps(DERIVED))
        return load_identity(cfg_path)

    def test_the_same_values_write_nothing(self, cfg_path):
        cfg = self.legacy(cfg_path)
        assert write_managed(cfg, cfg_path) is False
        assert not managed(cfg_path).exists()

    def test_a_change_to_a_table_it_sets_is_refused(self, cfg_path):
        cfg = self.legacy(cfg_path)
        with pytest.raises(WriterError, match=r"config.toml sets \[identity\]"):
            write_managed(replace(cfg, identity=Identity(login="other")), cfg_path)

    def test_a_pin_it_sets_is_refused(self, cfg_path):
        cfg = self.legacy(cfg_path)
        moved = replace(cfg, workspaces={"/abs/path": Workspace(role="co-author")})
        with pytest.raises(WriterError, match=r"sets \[workspaces\]"):
            write_managed(moved, cfg_path)

    def test_another_table_is_written(self, cfg_path):
        cfg_path.write_text('[identity]\nlogin = "bot"\n[github]\nprobe_repo = "o/r"\n')
        cfg = load_identity(cfg_path)
        write_managed(replace(cfg, github=Github(read_token_file="/t")), cfg_path)
        doc = tomllib.loads(managed(cfg_path).read_text())
        assert doc == {"github": {"read_token_file": "/t"}}
        assert load_identity(cfg_path).github.probe_repo == "o/r"


def test_no_carter_writer_opens_config_toml_for_writing():
    """The writers' targets, read from the source: one function opens a file for writing,
    and every call hands it the managed path."""
    src = (REPO / "carter/identity/writer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    atomic = [n for n in calls if getattr(n.func, "id", "") == "_atomic_write"]
    assert atomic and all(ast.unparse(n.args[0]) == "target" for n in atomic)
    assigned = [
        ast.unparse(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "target" for t in n.targets)
    ]
    assert assigned == ["managed_path(config_path)"]
    assert not [
        n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "config.toml"
    ]


def test_no_module_still_calls_the_old_config_writer():
    for path in (REPO / "carter").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "identity.writer import write_config" not in text, path
        assert "UnmodelledKeysError" not in text, path


def test_the_default_config_is_t0_and_writes_nothing_for_a_fresh_home(cfg_path):
    assert write_managed(EMPTY, cfg_path) is False
    assert list(cfg_path.parent.iterdir()) == []
