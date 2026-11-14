"""The schema-only TOML writer."""

from __future__ import annotations

import ast
import os
import stat
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from carter.identity import load_footer, load_identity
from carter.identity import writer as writer_mod
from carter.identity.schema import (
    Attribution,
    Identity,
    IdentityConfig,
    Signing,
    Workspace,
)
from carter.identity.writer import UnmodelledKeysError, WriterError, dumps, write_config

REPO = Path(__file__).resolve().parents[2]

FULL = IdentityConfig(
    identity=Identity(
        role="author",
        login="llm-bot",
        id=12345,
        name="llm-bot",
        email="12345+llm-bot@users.noreply.github.com",
        mode="review",
    ),
    signing=Signing(
        public_key_path="~/.ssh/llm-bot_signing.pub",
        public_key="ssh-ed25519 AAAAC3Nza",
        fingerprint="SHA256:abc",
        private_key_path="~/.ssh/llm-bot_signing",
        previous_public_keys=("ssh-ed25519 OLD1", "ssh-ed25519 OLD2"),
        agent_socket="/run/agent.sock",
        program="op-ssh-sign",
        ttl="4h",
        ssh_bin_dir="/opt/homebrew/bin",
    ),
    attribution=Attribution(footer="Generated with Carter."),
    workspaces={
        "/abs/path": Workspace(
            allow_project_opencode_edit=True,
            max_tier="t1",
            role="co-author",
            require_tier="t2",
        ),
        "/other": Workspace(),  # nothing pinned: an empty table must survive
    },
    state="current",
)
FULL = replace(FULL, disclosure=replace(FULL.disclosure, assisted_by=True))
EMPTY = IdentityConfig(state="current")


def same(a: IdentityConfig, b: IdentityConfig) -> bool:
    """Equal in everything the writer owns (not the read-time state/unknown_keys)."""
    return replace(a, state="current", unknown_keys=()) == replace(
        b, state="current", unknown_keys=()
    )


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestRoundTrip:
    @pytest.mark.parametrize("cfg", [FULL, EMPTY], ids=["full", "empty"])
    def test_tomllib_parses_what_was_dumped_and_the_reader_agrees(self, tmp_path, cfg):
        text = dumps(cfg)
        tomllib.loads(text)  # valid TOML

        path = tmp_path / "config.toml"
        write_config(cfg, path)

        assert same(load_identity(path), cfg)
        assert path.read_text(encoding="utf-8") == text

    def test_document_shape(self):
        doc = tomllib.loads(dumps(FULL))
        assert doc["schema"] == 2
        assert doc["identity"]["signing"]["previous_public_keys"] == [
            "ssh-ed25519 OLD1",
            "ssh-ed25519 OLD2",
        ]
        assert doc["identity"]["disclosure"] == {"assisted_by": True}
        assert doc["attribution"] == {"footer": "Generated with Carter."}
        assert doc["workspaces"]["/abs/path"] == {
            "allow_project_opencode_edit": True,
            "max_tier": "t1",
            "role": "co-author",
            "require_tier": "t2",
        }

    def test_empty_config_has_schema_and_no_workspaces(self):
        doc = tomllib.loads(dumps(EMPTY))
        assert doc["schema"] == 2
        assert "workspaces" not in doc

    def test_output_is_deterministic(self):
        assert dumps(FULL) == dumps(FULL)


class TestOnlyNonDefaultsAreStored:
    PARTIAL = replace(
        EMPTY,
        identity=Identity(login="llm-bot", id=12345),
        signing=Signing(public_key_path="~/.ssh/llm-bot.pub"),
        workspaces={"/w": Workspace(max_tier="t0")},
    )

    def test_a_default_config_is_the_header_and_the_schema(self):
        assert dumps(EMPTY).splitlines() == [writer_mod._HEADER, "schema = 2"]

    def test_the_header_says_what_is_stored_and_that_comments_go(self):
        assert "Only what you set is stored" in writer_mod._HEADER
        assert "drop comments" in writer_mod._HEADER

    def test_only_what_differs_is_written_and_empty_tables_are_left_out(self):
        text = dumps(self.PARTIAL)
        assert tomllib.loads(text) == {
            "schema": 2,
            "identity": {
                "login": "llm-bot",
                "id": 12345,
                "signing": {"public_key_path": "~/.ssh/llm-bot.pub"},
            },
            "workspaces": {"/w": {"max_tier": "t0"}},
        }
        for left_out in ("[attribution]", "[broker]", "disclosure", 'role = ""'):
            assert left_out not in text

    def test_a_value_equal_to_its_default_is_not_written(self):
        explicit = replace(
            EMPTY, identity=Identity(role="co-author"), signing=Signing(format="ssh")
        )
        assert dumps(explicit) == dumps(EMPTY)

    @pytest.mark.parametrize("cfg", [EMPTY, PARTIAL, FULL], ids=["empty", "partial", "full"])
    def test_what_is_stored_reads_back_equal(self, tmp_path, cfg):
        path = tmp_path / "config.toml"
        write_config(cfg, path)
        assert same(load_identity(path), cfg)
        assert dumps(load_identity(path)) == dumps(cfg)

    def test_a_fully_written_older_file_shrinks_on_its_first_rewrite(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            'schema = 2\n[identity]\nrole = "co-author"\nlogin = "bot"\nid = 0\n'
            '[attribution]\nfooter = "_This comment was generated with Carter._"\n'
            "[broker]\nmin_dwell_ms = 500\n"
        )
        cfg = load_identity(path)
        assert write_config(cfg, path) is True
        assert tomllib.loads(path.read_text()) == {"schema": 2, "identity": {"login": "bot"}}
        assert same(load_identity(path), cfg)

    def test_unset_workspace_enums_are_never_written_as_empty(self):
        text = dumps(replace(EMPTY, workspaces={"/w": Workspace(max_tier="t0")}))
        table = tomllib.loads(text)["workspaces"]["/w"]
        assert table == {"max_tier": "t0"}
        assert 'role = ""' not in text and 'require_tier = ""' not in text

    def test_whole_file_has_no_empty_enum(self):
        for line in dumps(FULL).splitlines() + dumps(EMPTY).splitlines():
            assert not line.startswith(('max_tier = ""', 'role = ""', 'require_tier = ""'))

    def test_written_file_is_accepted_by_the_reader(self, tmp_path):
        path = tmp_path / "config.toml"
        write_config(replace(EMPTY, workspaces={"/w": Workspace()}), path)
        assert load_identity(path).workspaces == {"/w": Workspace()}


HOSTILE_KEYS = [
    "/plain/path",
    '/with"quote',
    "/back\\slash",
    "/trailing\\",
    "/br]acket",
    "/[open",
    "/hash#tag",
    "/with space",
    "/tab\there",
    "/new\nline",
    "/nul\x00byte",
    "/del\x7fchar",
    "/dot.dot",
    "/eq=uals",
    "/single'quote",
    "/ñandú/日本語/🚀",
    "",
    " ",
    "/",
    "//",
    "..",
    "a" * 300,
    '"',
    "\\",
    '[workspaces."x"]',
]


class TestHostileWorkspaceKeys:
    @pytest.mark.parametrize("key", HOSTILE_KEYS, ids=lambda k: repr(k)[:30])
    def test_key_round_trips_through_tomllib(self, tmp_path, key):
        cfg = replace(EMPTY, workspaces={key: Workspace(max_tier="t1")})
        path = tmp_path / "config.toml"
        write_config(cfg, path)

        assert list(tomllib.loads(path.read_text(encoding="utf-8"))["workspaces"]) == [key]
        assert load_identity(path).workspaces == {key: Workspace(max_tier="t1")}

    def test_many_keys_together_stay_distinct(self, tmp_path):
        cfg = replace(EMPTY, workspaces={k: Workspace(max_tier="t0") for k in HOSTILE_KEYS})
        path = tmp_path / "config.toml"
        write_config(cfg, path)
        assert set(load_identity(path).workspaces) == set(HOSTILE_KEYS)


class TestStringEscaping:
    @pytest.mark.parametrize(
        "value",
        [
            'quote " inside',
            "back\\slash",
            "line1\nline2",
            "cr\r\nlf",
            "tab\there",
            "bell\x07 esc\x1b nul\x00 del\x7f",
            "'''triple''' \"\"\"double\"\"\"",
            "unicode ñ 日本 🚀",
            "trailing backslash\\",
            "",
        ],
    )
    def test_strings_survive(self, tmp_path, value):
        cfg = replace(EMPTY, attribution=Attribution(footer=value), identity=Identity(name=value))
        path = tmp_path / "config.toml"
        write_config(cfg, path)
        again = load_identity(path)
        assert again.attribution.footer == value
        assert again.identity.name == value

    def test_ints_bools_and_lists(self, tmp_path):
        cfg = replace(
            EMPTY,
            identity=Identity(id=2**40),
            signing=Signing(previous_public_keys=()),
        )
        cfg = replace(cfg, disclosure=replace(cfg.disclosure, assisted_by=False))
        path = tmp_path / "config.toml"
        write_config(cfg, path)
        again = load_identity(path)
        assert again.identity.id == 2**40
        assert again.signing.previous_public_keys == ()
        assert again.disclosure.assisted_by is False


class TestRefusesToWriteWhatTheReaderRejects:
    @pytest.mark.parametrize(
        "bad",
        [
            Identity(role="root"),
            Identity(role=""),
            Identity(login=5),  # type: ignore[arg-type]
        ],
    )
    def test_invalid_identity_is_refused(self, tmp_path, bad):
        with pytest.raises(WriterError):
            write_config(replace(EMPTY, identity=bad), tmp_path / "config.toml")
        assert not (tmp_path / "config.toml").exists()

    def test_invalid_workspace_enum_is_refused(self, tmp_path):
        cfg = replace(EMPTY, workspaces={"/w": Workspace(max_tier="t2")})
        with pytest.raises(WriterError):
            write_config(cfg, tmp_path / "config.toml")


class TestAtomicWrite:
    def test_failed_replace_leaves_original_and_no_tmp(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        write_config(EMPTY, path)
        original = path.read_bytes()

        def boom(*_a, **_k):
            raise OSError("disk on fire")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="disk on fire"):
            write_config(FULL, path)

        assert path.read_bytes() == original
        assert [p.name for p in tmp_path.iterdir()] == ["config.toml"]

    def test_failed_first_write_leaves_nothing_behind(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
        with pytest.raises(OSError):
            write_config(FULL, tmp_path / "config.toml")
        assert list(tmp_path.iterdir()) == []

    def test_data_is_fsynced_before_the_replace(self, tmp_path, monkeypatch):
        calls: list[str] = []
        real_fsync, real_replace = os.fsync, os.replace
        monkeypatch.setattr(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
        monkeypatch.setattr(
            os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[1]
        )
        write_config(FULL, tmp_path / "config.toml")
        assert "fsync" in calls and "replace" in calls
        assert calls.index("fsync") < calls.index("replace")

    def test_tmp_file_is_in_the_same_directory(self, tmp_path, monkeypatch):
        seen: list[tuple[str, str]] = []
        real = os.replace
        monkeypatch.setattr(os, "replace", lambda a, b: (seen.append((a, b)), real(a, b))[1])
        write_config(FULL, tmp_path / "config.toml")
        ((src, dst),) = seen
        assert Path(src).parent == Path(dst).parent == tmp_path

    def test_mode_is_0600_even_if_umask_is_open(self, tmp_path):
        old = os.umask(0)
        try:
            path = tmp_path / "config.toml"
            write_config(FULL, path)
        finally:
            os.umask(old)
        assert mode(path) == 0o600

    def test_rewrite_tightens_a_loose_existing_mode(self, tmp_path):
        path = tmp_path / "config.toml"
        write_config(EMPTY, path)
        path.chmod(0o644)
        write_config(FULL, path)
        assert mode(path) == 0o600

    def test_creates_missing_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "carter" / "config.toml"
        write_config(FULL, path)
        assert same(load_identity(path), FULL)


OLD_KEYS = '[attribution]\nname = "carter-bot"\nfooter = "_Mine._"\n\n[git]\nsigning_key = "/k"\n'
EXISTING = 'schema = 2\n[attribution]\nfooter = "_Mine._"\n'  # a valid file a command rewrites


class TestBackup:
    def test_backup_is_written_once_with_the_original_bytes(self, tmp_path):
        path, bak = tmp_path / "config.toml", tmp_path / "config.toml.bak"
        path.write_text(EXISTING)

        write_config(FULL, path, backup_to=bak)

        assert bak.read_text() == EXISTING
        assert mode(bak) == 0o600
        assert same(load_identity(path), FULL)

    def test_existing_backup_is_never_overwritten(self, tmp_path):
        path, bak = tmp_path / "config.toml", tmp_path / "config.toml.bak"
        path.write_text(EXISTING)
        bak.write_text("PRECIOUS")

        write_config(FULL, path, backup_to=bak)

        assert bak.read_text() == "PRECIOUS"

    def test_no_backup_when_there_is_nothing_to_back_up(self, tmp_path):
        bak = tmp_path / "config.toml.bak"
        write_config(FULL, tmp_path / "config.toml", backup_to=bak)
        assert not bak.exists()

    def test_backup_survives_a_failed_replace(self, tmp_path, monkeypatch):
        path, bak = tmp_path / "config.toml", tmp_path / "config.toml.bak"
        path.write_text(EXISTING)
        monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
        with pytest.raises(OSError):
            write_config(FULL, path, backup_to=bak)
        assert path.read_text() == EXISTING
        assert bak.read_text() == EXISTING
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted([bak.name, path.name])

    def test_a_file_with_old_keys_is_never_rewritten_even_with_a_backup(self, tmp_path):
        path, bak = tmp_path / "config.toml", tmp_path / "config.toml.bak"
        path.write_text(OLD_KEYS)
        with pytest.raises(UnmodelledKeysError):
            write_config(FULL, path, backup_to=bak)
        assert path.read_text() == OLD_KEYS and not bak.exists()


class TestIdempotent:
    def test_second_identical_write_changes_nothing(self, tmp_path):
        path, bak = tmp_path / "config.toml", tmp_path / "config.toml.bak"
        path.write_text(EXISTING)

        assert write_config(FULL, path, backup_to=bak) is True
        first = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        bak_bytes = bak.read_bytes()

        assert write_config(FULL, path, backup_to=bak) is False
        assert path.read_bytes() == first
        assert path.stat().st_mtime_ns == mtime
        assert bak.read_bytes() == bak_bytes
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted([bak.name, path.name])

    def test_dumps_is_stable_through_a_read_write_cycle(self, tmp_path):
        path = tmp_path / "config.toml"
        write_config(FULL, path)
        first = path.read_bytes()
        write_config(load_identity(path), path)
        assert path.read_bytes() == first


class TestRefusesUnmodelledKeys:
    def test_unknown_keys_block_the_rewrite_and_print_a_diff(self, tmp_path):
        path = tmp_path / "config.toml"
        text = dumps(EMPTY) + "\n[extra]\nprecious = 1\n"
        path.write_text(text)

        with pytest.raises(UnmodelledKeysError) as exc:
            write_config(FULL, path)

        assert path.read_text() == text  # untouched
        assert exc.value.keys == ("extra.precious",)
        assert "-precious = 1" in exc.value.diff
        assert "+" in exc.value.diff
        assert "precious" in str(exc.value)  # the printed diff
        assert [p.name for p in tmp_path.iterdir()] == ["config.toml"]

    def test_unknown_key_inside_a_known_table(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('schema = 2\n[identity]\nlogin = "bot"\nsurprise = "x"\n')
        with pytest.raises(UnmodelledKeysError) as exc:
            write_config(FULL, path)
        assert exc.value.keys == ("identity.surprise",)

    def test_a_broken_existing_file_is_not_overwritten(self, tmp_path):
        from carter.identity import ConfigError

        path = tmp_path / "config.toml"
        path.write_text("schema = 2\n[identity\n")
        with pytest.raises(ConfigError):
            write_config(FULL, path)
        assert path.read_text() == "schema = 2\n[identity\n"

    def test_future_schema_is_not_overwritten(self, tmp_path):
        from carter.identity import ConfigError

        path = tmp_path / "config.toml"
        path.write_text("schema = 3\n")
        with pytest.raises(ConfigError):
            write_config(FULL, path)
        assert path.read_text() == "schema = 3\n"


class TestReadsNeverWrite:
    def test_loaders_do_not_reach_the_writer(self, tmp_path, monkeypatch):
        def trap(*_a, **_k):
            raise AssertionError("a read path called the writer")

        monkeypatch.setattr(writer_mod, "write_config", trap)
        monkeypatch.setattr(writer_mod, "dumps", trap)
        path = tmp_path / "config.toml"
        path.write_text(dumps(FULL))
        load_identity(path)
        load_footer(path)
        load_identity(tmp_path / "missing.toml")

    def test_only_explicit_commands_import_the_writer(self):
        allowed = {
            "carter/identity/writer.py",
            "carter/install/components.py",  # `carter install` creates the defaults
            "carter/identity/pin.py",  # only `carter update` calls it
            "carter/cli.py",  # `carter update` (lazy import, WriterError)
            "carter/ghtoken.py",  # only `github-token set` calls it (records read_token_file)
            "carter/identity_add.py",  # `identity add` (explicit, human terminal)
            "carter/identity_remove.py",  # `identity remove` (explicit, human terminal)
        }
        importers = set()
        for src in (REPO / "carter").rglob("*.py"):
            tree = ast.parse(src.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
                elif isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                if any(m == "carter.identity.writer" for m in mods):
                    importers.add(str(src.relative_to(REPO)))
        assert importers <= allowed, importers - allowed

    def test_package_init_does_not_pull_the_writer_in(self):
        text = (REPO / "carter" / "identity" / "__init__.py").read_text()
        assert "writer" not in text


class TestSize:
    def test_writer_code_stays_small(self):
        """About 120 lines. Counts code only (no blanks, comments or docstrings)."""
        src = (REPO / "carter" / "identity" / "writer.py").read_text()
        tree = ast.parse(src)
        doc_lines: set[int] = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            first = body[0] if isinstance(body, list) and body else None
            if (
                first is not None
                and isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc_lines.update(range(first.lineno, first.end_lineno + 1))
        code = [
            ln
            for i, ln in enumerate(src.splitlines(), 1)
            if ln.strip() and not ln.strip().startswith("#") and i not in doc_lines
        ]
        assert len(code) <= 120, len(code)
