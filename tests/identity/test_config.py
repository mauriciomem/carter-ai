"""The schema-2 reader (RFC-0007 §4.1): typed, tomllib-based, read-only.

Covers plan 002 step 6: round-trip of every RFC key, schema-1 recognition (never
reinterpreted), the split error paths (identity fails closed, footer degrades) and
the "reads never write" rule.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import os
import textwrap
from pathlib import Path

import pytest

from carter.identity import (
    ConfigError,
    load_footer,
    load_identity,
    schema_names,
)
from carter.identity.config import DEFAULT_FOOTER
from carter.identity.schema import Identity, Signing, Workspace

# The RFC §4.1 example, key for key (values made concrete).
SCHEMA2 = textwrap.dedent(
    """\
    schema = 2
    [identity]
    role = "author"
    login = "llm-bot"
    id = 12345
    name = "llm-bot"
    email = "12345+llm-bot@users.noreply.github.com"
    mode = "review"
    [identity.signing]
    format = "ssh"
    public_key_path = "~/.ssh/llm-bot_signing.pub"
    public_key = "ssh-ed25519 AAAAC3Nza"
    fingerprint = "SHA256:abc"
    private_key_path = "~/.ssh/llm-bot_signing"
    previous_public_keys = ["ssh-ed25519 OLD1", "ssh-ed25519 OLD2"]
    agent_socket = "/run/agent.sock"
    program = "op-ssh-sign"
    ttl = "4h"
    ssh_bin_dir = "/opt/homebrew/bin"
    [identity.disclosure]
    assisted_by = true
    [attribution]
    footer = "Generated with Carter."
    [github]
    read_token_file = "~/.carter/secrets/gh-read.token"
    [workspaces."/abs/path"]
    allow_project_opencode_edit = true
    max_tier = "t1"
    role = "co-author"
    require_tier = "t2"
    """
)

SCHEMA1 = textwrap.dedent(
    """\
    [attribution]
    name = "carter-bot"
    email = "carter-bot@users.noreply.github.com"
    footer = "_Legacy footer._"

    [git]
    signing_key = "/home/dev/.ssh/id_ed25519"
    """
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def digest(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


class TestSchema2Parses:
    def test_every_rfc_key_round_trips_by_name(self, tmp_path):
        cfg = load_identity(write(tmp_path, SCHEMA2))

        assert cfg.state == "current"
        assert cfg.schema == 2
        assert cfg.identity == Identity(
            role="author",
            login="llm-bot",
            id=12345,
            name="llm-bot",
            email="12345+llm-bot@users.noreply.github.com",
            mode="review",
        )
        assert cfg.signing == Signing(
            format="ssh",
            public_key_path="~/.ssh/llm-bot_signing.pub",
            public_key="ssh-ed25519 AAAAC3Nza",
            fingerprint="SHA256:abc",
            private_key_path="~/.ssh/llm-bot_signing",
            previous_public_keys=("ssh-ed25519 OLD1", "ssh-ed25519 OLD2"),
            agent_socket="/run/agent.sock",
            program="op-ssh-sign",
            ttl="4h",
            ssh_bin_dir="/opt/homebrew/bin",
        )
        assert cfg.disclosure.assisted_by is True
        assert cfg.attribution.footer == "Generated with Carter."
        assert cfg.github.read_token_file == "~/.carter/secrets/gh-read.token"
        assert cfg.workspaces == {
            "/abs/path": Workspace(
                allow_project_opencode_edit=True,
                max_tier="t1",
                role="co-author",
                require_tier="t2",
            )
        }
        assert cfg.unknown_keys == ()

    def test_paths_and_keys_are_not_expanded(self, tmp_path):
        # The key literal must never be expanduser'd; the reader stays pure.
        cfg = load_identity(write(tmp_path, SCHEMA2))
        assert cfg.signing.public_key_path.startswith("~/")
        assert cfg.signing.public_key == "ssh-ed25519 AAAAC3Nza"

    def test_minimal_file_gets_defaults(self, tmp_path):
        cfg = load_identity(write(tmp_path, "schema = 2\n"))
        assert cfg.state == "current"
        assert cfg.identity == Identity()
        assert cfg.identity.role == "co-author"
        assert cfg.signing.ttl == "8h"
        assert cfg.signing.format == "ssh"
        assert cfg.signing.ssh_bin_dir == "/usr/bin"  # RFC §4.6 default (Apple OpenSSH)
        assert cfg.workspaces == {}

    @pytest.mark.parametrize(
        "path",
        ['/p/"q"', "/p/back\\slash", "/p/a]b", "/p/#hash", "/p/with space", "/p/ñandú/日本"],
        ids=["quote", "backslash", "bracket", "hash", "space", "unicode"],
    )
    def test_awkward_workspace_keys_survive(self, tmp_path, path):
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        text = f'schema = 2\n[workspaces."{escaped}"]\nmax_tier = "t0"\n'
        cfg = load_identity(write(tmp_path, text))
        assert list(cfg.workspaces) == [path]
        assert cfg.workspaces[path].max_tier == "t0"

    def test_unmodelled_keys_are_reported_not_dropped_silently(self, tmp_path):
        text = SCHEMA2 + "[identity.future]\nx = 1\n[extra]\ny = 2\n"
        text = text.replace('mode = "review"', 'mode = "review"\nsurprise = "x"')
        cfg = load_identity(write(tmp_path, text))
        assert set(cfg.unknown_keys) == {"identity.surprise", "identity.future", "extra"}


class TestSchema1IsRecognisedNotReinterpreted:
    def test_schema1_without_schema_key_needs_migration(self, tmp_path):
        cfg = load_identity(write(tmp_path, SCHEMA1))
        assert cfg.state == "needs_migration"
        assert cfg.needs_migration is True

    def test_explicit_schema_1_needs_migration(self, tmp_path):
        cfg = load_identity(write(tmp_path, "schema = 1\n" + SCHEMA1))
        assert cfg.state == "needs_migration"

    def test_legacy_values_never_leak_into_identity(self, tmp_path):
        cfg = load_identity(write(tmp_path, SCHEMA1))
        assert cfg.identity == Identity()
        assert cfg.signing == Signing()
        dumped = repr(dataclasses.asdict(cfg))
        assert "carter-bot@" not in dumped  # the legacy email
        assert "id_ed25519" not in dumped  # the human's key path
        assert "Legacy footer" not in dumped  # footers come from load_footer()

    def test_empty_file_is_not_a_migration(self, tmp_path):
        cfg = load_identity(write(tmp_path, "# only a comment\n"))
        assert cfg.state == "absent"
        assert cfg.needs_migration is False

    @pytest.mark.parametrize("schema", ["3", "0", '"2"', "true", "2.0"])
    def test_unsupported_schema_fails_closed(self, tmp_path, schema):
        with pytest.raises(ConfigError) as exc:
            load_identity(write(tmp_path, f"schema = {schema}\n"))
        assert exc.value.code == "E-CONFIG"
        assert "schema" in exc.value.detail


class TestMissingFile:
    def test_missing_file_is_t0_defaults_without_error(self, tmp_path):
        cfg = load_identity(tmp_path / "nope.toml")
        assert cfg.state == "absent"
        assert cfg.identity == Identity()
        assert cfg.signing == Signing()
        assert not (tmp_path / "nope.toml").exists()  # reading never creates it

    def test_default_path_is_the_hermetic_carter_home(self):
        # conftest points HOME at a temp dir: no file there, so defaults.
        assert load_identity().state == "absent"
        assert load_footer().footer == DEFAULT_FOOTER


class TestIdentityFailsClosed:
    @pytest.mark.parametrize(
        "text",
        [
            "schema = 2\n[identity\n",  # TOML syntax error
            "schema = 2\nschema = 2\n",  # duplicate key
            'schema = 2\n[identity]\nid = "12"\n',  # wrong type
            "schema = 2\n[identity]\nid = true\n",  # bool is not an int here
            "schema = 2\n[identity]\nlogin = 5\n",
            'schema = 2\n[identity]\nrole = "root"\n',  # not in enum
            'schema = 2\n[identity.signing]\nformat = "gpg"\n',  # v1: ssh only
            'schema = 2\n[identity.signing]\nprevious_public_keys = "x"\n',
            "schema = 2\n[identity.signing]\nprevious_public_keys = [1]\n",
            'schema = 2\n[identity.disclosure]\nassisted_by = "yes"\n',
            'schema = 2\n[workspaces."/p"]\nmax_tier = "t2"\n',  # cap is t0|t1
            'schema = 2\n[workspaces."/p"]\nrequire_tier = "t9"\n',
            'schema = 2\n[workspaces."/p"]\nrole = "god"\n',
            "schema = 2\nidentity = 3\n",  # table expected
            "schema = 2\n[workspaces]\nx = 1\n",  # workspace entries are tables
        ],
    )
    def test_invalid_config_raises_e_config(self, tmp_path, text):
        with pytest.raises(ConfigError) as exc:
            load_identity(write(tmp_path, text))
        assert exc.value.code == "E-CONFIG"
        assert "disabled" in str(exc.value)  # the App B message
        assert exc.value.detail

    def test_invalid_utf8_raises_e_config(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_bytes(b'schema = 2\n[identity]\nname = "\xff\xfe"\n')
        with pytest.raises(ConfigError):
            load_identity(path)

    def test_unreadable_path_raises_e_config(self, tmp_path):
        directory = tmp_path / "config.toml"
        directory.mkdir()  # exists but cannot be read as a file
        with pytest.raises(ConfigError):
            load_identity(directory)

    def test_error_detail_never_echoes_secret_values(self, tmp_path):
        text = (
            "schema = 2\n[identity.signing]\nprivate_key_path = 5\n"
            'public_key = "ssh-ed25519 SECRET"\n'
        )
        with pytest.raises(ConfigError) as exc:
            load_identity(write(tmp_path, text))
        assert "SECRET" not in str(exc.value) + exc.value.detail


class TestFooterDegrades:
    def test_malformed_toml_gives_default_footer_and_a_warning(self, tmp_path):
        result = load_footer(write(tmp_path, "schema = 2\n[identity\n"))
        assert result.footer == DEFAULT_FOOTER
        assert result.warning is not None
        assert "footer" in result.warning

    def test_footer_loads_even_when_identity_is_invalid(self, tmp_path):
        text = SCHEMA2.replace('role = "author"', 'role = "root"')
        result = load_footer(write(tmp_path, text))
        assert result.footer == "Generated with Carter."
        assert result.warning is None

    def test_schema1_footer_is_kept(self, tmp_path):
        result = load_footer(write(tmp_path, SCHEMA1))
        assert result.footer == "_Legacy footer._"
        assert result.warning is None

    def test_missing_file_and_missing_footer_use_the_default_silently(self, tmp_path):
        assert load_footer(tmp_path / "nope.toml").warning is None
        assert load_footer(write(tmp_path, "schema = 2\n")).footer == DEFAULT_FOOTER

    @pytest.mark.parametrize("text", ["[attribution]\nfooter = 5\n", "attribution = 1\n"])
    def test_wrong_typed_footer_degrades_with_a_warning(self, tmp_path, text):
        result = load_footer(write(tmp_path, text))
        assert result.footer == DEFAULT_FOOTER
        assert result.warning is not None

    def test_unreadable_footer_source_degrades(self, tmp_path):
        directory = tmp_path / "config.toml"
        directory.mkdir()
        result = load_footer(directory)
        assert result.footer == DEFAULT_FOOTER
        assert result.warning is not None


class TestReadsNeverWrite:
    @pytest.mark.parametrize("text", [SCHEMA2, SCHEMA1, "schema = 2\n[identity\n", ""])
    def test_loaders_leave_the_file_untouched(self, tmp_path, text):
        path = write(tmp_path, text)
        before = digest(path)

        for load in (load_identity, load_footer):
            with contextlib.suppress(ConfigError):
                load(path)

        assert digest(path) == before
        assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml"]  # no .bak/.tmp

    def test_loading_does_not_create_the_carter_home(self):
        home = Path(os.environ["HOME"]) / ".carter"
        load_identity()
        load_footer()
        assert not home.exists()


class TestSchemaNames:
    def test_schema_names_cover_the_rfc_example(self):
        names = schema_names()
        assert names[""] == ("schema",)
        assert names["identity"] == ("role", "login", "id", "name", "email", "mode")
        assert "previous_public_keys" in names["identity.signing"]
        assert names["identity.disclosure"] == ("assisted_by",)
        assert names["attribution"] == ("footer",)
        assert names["github"] == ("read_token_file", "probe_repo")
        assert names['workspaces."<abs path>"'] == (
            "allow_project_opencode_edit",
            "max_tier",
            "role",
            "require_tier",
        )
