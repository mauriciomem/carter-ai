"""``~/.carter/guard-state.json`` (RFC-0007 App C.6.1; plan 003 step 9, freeze F2)."""

from __future__ import annotations

import ast
import json
import os
import stat
from pathlib import Path

import pytest

from carter.guard import state as gs
from carter.guard.state import GuardState
from carter.identity import IdentityError
from carter.identity.errors import E_STATE_INVALID
from carter.install.ownership import sha256_bytes
from carter.install.paths import guard_state_path


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "carter" / "guard-state.json"


def full_state() -> GuardState:
    st = GuardState()
    st.consent("g2", "accepted", "2026-11-02")
    st.record_policy("deny-git-push", "tool.use", "shell:git push *", "deny", preexisting=False)
    st.record_permission("build", "permission.carter_push", "deny", preexisting=False)
    st.record_gitconfig("/h/.gitconfig", "/h/.carter/gitconfig")
    return st


class TestShapeIsFrozen:
    def test_top_level_keys_in_order(self) -> None:
        assert gs.STATE_KEYS == (
            "schema",
            "consents",
            "files",
            "gitconfig",
            "git_config",
            "opencode_config",
            "opencode_policies",
            "agent_permissions",
            "repo_hooks",
            "guard_version",
        )

    def test_entry_fields(self) -> None:
        assert gs.CONSENT_FIELDS == ("decision", "date", "rev")
        assert gs.FILE_FIELDS == ("path", "sha256")
        assert gs.POLICY_FIELDS == ("id", "action", "resource", "effect", "preexisting")
        assert gs.PERMISSION_FIELDS == ("agent", "key", "value", "preexisting")
        assert gs.GITCONFIG_FIELDS == ("file", "key", "value")
        assert gs.GIT_CONFIG_FIELDS == ("file", "key", "value", "scope")
        assert gs.REPO_HOOK_FIELDS == ("path", "sha256")

    def test_an_empty_state_has_every_key_with_the_1g_defaults(self, path: Path) -> None:
        data = GuardState().to_dict()
        assert tuple(data) == gs.STATE_KEYS
        assert data["schema"] == 1
        assert data["consents"] == {} and data["files"] == [] and data["git_config"] == []
        assert data["gitconfig"] is None and data["guard_version"] is None
        assert data["opencode_config"] is None and data["repo_hooks"] == []

    def test_path_helper_honours_the_base_dir_override(self, tmp_path: Path) -> None:
        assert guard_state_path(tmp_path) == tmp_path / "carter" / "guard-state.json"
        assert guard_state_path(None) == Path.home() / ".carter" / "guard-state.json"


class TestRoundTrip:
    def test_missing_file_loads_empty(self, path: Path) -> None:
        assert gs.load(path) == GuardState()

    def test_save_then_load_is_equal(self, path: Path) -> None:
        st = full_state()
        gs.save(st, path)
        assert gs.load(path) == st

    def test_file_is_0600_and_a_new_directory_0700(self, path: Path) -> None:
        gs.save(full_state(), path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_an_existing_directory_keeps_its_mode(self, path: Path) -> None:
        path.parent.mkdir(parents=True, mode=0o755)
        path.parent.chmod(0o755)
        gs.save(full_state(), path)
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o755

    def test_output_is_pretty_json_with_trailing_newline(self, path: Path) -> None:
        gs.save(full_state(), path)
        text = path.read_text()
        assert text.endswith("}\n") and text.startswith('{\n  "schema": 1')

    def test_saving_an_equal_state_writes_nothing(self, path: Path) -> None:
        gs.save(full_state(), path)
        before = path.stat()
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        assert gs.save(full_state(), path) is False
        assert path.stat().st_mtime_ns == 1_000_000_000
        assert before.st_ino == path.stat().st_ino

    def test_saving_a_change_reports_true(self, path: Path) -> None:
        gs.save(GuardState(), path)
        assert gs.save(full_state(), path) is True


class TestAtomicWrite:
    def test_failure_at_replace_keeps_the_old_file_and_leaves_no_tmp(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gs.save(full_state(), path)
        before = path.read_bytes()

        def boom(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        changed = GuardState()
        with pytest.raises(OSError, match="disk full"):
            gs.save(changed, path)
        assert path.read_bytes() == before
        assert sorted(p.name for p in path.parent.iterdir()) == ["guard-state.json"]

    def test_failure_at_fsync_keeps_the_old_file_and_leaves_no_tmp(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gs.save(full_state(), path)
        before = path.read_bytes()
        monkeypatch.setattr(os, "fsync", lambda *_a: (_ for _ in ()).throw(OSError("io")))
        with pytest.raises(OSError):
            gs.save(GuardState(), path)
        assert path.read_bytes() == before
        assert sorted(p.name for p in path.parent.iterdir()) == ["guard-state.json"]

    def test_fsync_is_called_before_the_replace(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order: list[str] = []
        real_fsync, real_replace = os.fsync, os.replace
        monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
        monkeypatch.setattr(
            os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1]
        )
        gs.save(full_state(), path)
        assert order[:2] == ["fsync", "replace"]

    def test_tmp_file_is_next_to_the_target(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Path] = []
        real_replace = os.replace
        monkeypatch.setattr(
            os, "replace", lambda a, b: (seen.append(Path(a)), real_replace(a, b))[1]
        )
        gs.save(full_state(), path)
        assert seen[0].parent == path.parent


class TestInPlaceUpdate:
    def test_adding_a_consent_keeps_every_other_field(self, path: Path) -> None:
        gs.save(full_state(), path)
        st = gs.load(path)
        st.consent("sudo-docker", "declined", "2026-11-03")
        gs.save(st, path)
        again = gs.load(path)
        assert again.opencode_policies == full_state().opencode_policies
        assert again.agent_permissions == full_state().agent_permissions
        assert again.gitconfig == full_state().gitconfig
        assert again.consents["g2"] == {"decision": "accepted", "date": "2026-11-02", "rev": 1}
        assert again.consents["sudo-docker"]["decision"] == "declined"

    def test_unknown_top_level_keys_survive_a_load_save(self, path: Path) -> None:
        data = full_state().to_dict()
        data["from_a_newer_carter"] = {"x": [1, 2]}
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data))
        st = gs.load(path)
        st.consent("alias", "declined", "2026-11-03")
        gs.save(st, path)
        assert json.loads(path.read_text())["from_a_newer_carter"] == {"x": [1, 2]}

    def test_a_lower_guard_version_never_overwrites_a_higher_one(self) -> None:
        st = GuardState()
        st.set_guard_version("1.4.0")
        assert st.set_guard_version("1.3.9") is False
        assert st.guard_version == "1.4.0"
        assert st.set_guard_version("1.4.1") is True
        assert st.set_guard_version("1.2.0", force=True) is True
        assert st.guard_version == "1.2.0"

    def test_recording_the_same_id_replaces_not_duplicates(self) -> None:
        st = GuardState()
        st.record_policy("a", "tool.use", "shell:x *", "deny", preexisting=False)
        st.record_policy("a", "tool.use", "shell:y *", "deny", preexisting=False)
        assert [p["resource"] for p in st.opencode_policies] == ["shell:y *"]

    def test_unconsent_is_not_a_thing_but_a_change_of_mind_replaces(self) -> None:
        st = GuardState()
        st.consent("g2", "declined", "2026-11-02")
        st.consent("g2", "accepted", "2026-11-05")
        assert st.consents["g2"]["decision"] == "accepted"

    def test_bad_consent_values_are_refused(self) -> None:
        with pytest.raises(ValueError):
            GuardState().consent("g2", "maybe", "2026-11-02")
        with pytest.raises(ValueError):
            GuardState().consent("g2", "accepted", "yesterday")


class TestDowngradeSurvival:
    def test_an_older_installer_rebuilding_the_manifest_leaves_guard_state_alone(
        self, tmp_path: Path
    ) -> None:
        from carter.install.components import write_manifest

        target = guard_state_path(tmp_path)
        gs.save(full_state(), target)
        before = target.read_bytes()
        # What every older `carter install` does: rebuild manifest.json from scratch.
        write_manifest(
            {"version": "0.16.0", "files": [], "mcp_servers": [], "file_hashes": {}}, tmp_path
        )
        assert target.read_bytes() == before
        manifest = (tmp_path / "carter" / "manifest.json").read_text()
        assert "opencode_policies" not in manifest and "consents" not in manifest

    def test_manifest_module_knows_nothing_about_guard_state(self) -> None:
        source = Path(gs.__file__).parent.parent / "install" / "components.py"
        assert "guard-state" not in source.read_text(encoding="utf-8")


class TestFilesAndHashes:
    def test_record_file_uses_the_ownership_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "x"
        f.write_bytes(b"hello")
        st = GuardState()
        st.record_file(f, b"hello")
        assert st.files == [{"path": str(f), "sha256": sha256_bytes(b"hello")}]
        assert st.files[0]["sha256"].startswith("sha256:")

    def test_owned_unchanged_is_true_only_when_the_hash_matches(self, tmp_path: Path) -> None:
        f = tmp_path / "x"
        f.write_bytes(b"hello")
        st = GuardState()
        st.record_file(f, b"hello")
        assert st.owned_unchanged(f) is True
        f.write_bytes(b"hello!")
        assert st.owned_unchanged(f) is False

    def test_missing_file_or_unrecorded_file_is_false_without_raising(self, tmp_path: Path) -> None:
        st = GuardState()
        assert st.owned_unchanged(tmp_path / "nope") is False
        st.record_file(tmp_path / "gone", b"x")
        assert st.owned_unchanged(tmp_path / "gone") is False

    def test_a_directory_in_place_of_the_file_is_false(self, tmp_path: Path) -> None:
        st = GuardState()
        st.record_file(tmp_path, b"x")
        assert st.owned_unchanged(tmp_path) is False

    def test_forget_file(self, tmp_path: Path) -> None:
        st = GuardState()
        st.record_file(tmp_path / "a", b"1")
        st.forget_file(tmp_path / "a")
        assert st.files == []


class TestPoliciesAndPermissions:
    def test_policy_tuples_have_the_frozen_fields(self) -> None:
        st = GuardState()
        st.record_policy("deny-sudo", "tool.use", "shell:sudo *", "deny", preexisting=False)
        assert tuple(st.opencode_policies[0]) == gs.POLICY_FIELDS

    def test_preexisting_entries_are_never_owned(self) -> None:
        st = GuardState()
        st.record_policy("deny-sudo", "tool.use", "shell:sudo *", "deny", preexisting=True)
        st.record_policy("deny-docker", "tool.use", "shell:docker *", "deny", preexisting=False)
        assert [p["id"] for p in st.owned_policies()] == ["deny-docker"]
        assert [p["id"] for p in st.opencode_policies] == ["deny-sudo", "deny-docker"]

    def test_permission_entries(self) -> None:
        st = GuardState()
        st.record_permission("build", "permission.carter_push", "deny", preexisting=False)
        st.record_permission("plan", "permission.carter_push", "deny", preexisting=True)
        assert tuple(st.agent_permissions[0]) == gs.PERMISSION_FIELDS
        assert [p["agent"] for p in st.owned_permissions()] == ["build"]

    def test_gitconfig_is_a_single_entry_and_the_fallback_is_a_list(self) -> None:
        st = GuardState()
        st.record_gitconfig("/h/.gitconfig", "/h/.carter/gitconfig")
        assert st.gitconfig == {
            "file": "/h/.gitconfig",
            "key": "include.path",
            "value": "/h/.carter/gitconfig",
        }
        st.record_git_config("/h/.gitconfig", "hook.x.event", "commit-msg", "global")
        assert st.git_config == [
            {
                "file": "/h/.gitconfig",
                "key": "hook.x.event",
                "value": "commit-msg",
                "scope": "global",
            }
        ]
        st.clear_gitconfig()
        assert st.gitconfig is None

    def test_opencode_config_records_the_written_path(self) -> None:
        st = GuardState()
        st.opencode_config = "/h/.config/opencode/opencode.jsonc"
        assert st.to_dict()["opencode_config"] == "/h/.config/opencode/opencode.jsonc"


class TestCorruption:
    def test_load_raises_a_typed_error_for_invalid_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        with pytest.raises(IdentityError) as exc:
            gs.load(path)
        assert exc.value.code == E_STATE_INVALID

    @pytest.mark.parametrize(
        "content",
        [
            "[]",
            "{}",  # no schema
            '{"schema": "1"}',
            '{"schema": 2}',  # from the future
            '{"schema": 1, "consents": []}',
            '{"schema": 1, "opencode_policies": {"a": 1}}',
            '{"schema": 1, "opencode_policies": ["x"]}',
            '{"schema": 1, "gitconfig": "x"}',
            '{"schema": 1, "guard_version": 3}',
        ],
    )
    def test_load_refuses_a_wrong_shape_or_a_newer_schema(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True)
        path.write_text(content)
        with pytest.raises(IdentityError) as exc:
            gs.load(path)
        assert exc.value.code == E_STATE_INVALID

    def test_a_refused_file_is_never_rebuilt_by_load_or_save_of_a_loaded_state(
        self, path: Path
    ) -> None:
        path.parent.mkdir(parents=True)
        path.write_text('{"schema": 2}')
        with pytest.raises(IdentityError):
            gs.load(path)
        assert path.read_text() == '{"schema": 2}'

    def test_error_detail_names_the_key_not_the_value(self, path: Path) -> None:
        path.parent.mkdir(parents=True)
        path.write_text('{"schema": 1, "guard_version": "super-secret-token-value", "consents": 5}')
        with pytest.raises(IdentityError) as exc:
            gs.load(path)
        assert "consents" in exc.value.detail
        assert "super-secret" not in exc.value.detail

    def test_readonly_reader_reports_without_raising_or_writing(self, path: Path) -> None:
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        result = gs.load_or_empty_readonly(path)
        assert result.status == "corrupt" and result.state == GuardState() and result.detail
        assert path.read_text() == "{broken"
        assert sorted(p.name for p in path.parent.iterdir()) == ["guard-state.json"]

    def test_readonly_reader_statuses(self, path: Path) -> None:
        assert gs.load_or_empty_readonly(path).status == "absent"
        gs.save(full_state(), path)
        ok = gs.load_or_empty_readonly(path)
        assert ok.status == "ok" and ok.state == full_state()
        path.write_text('{"schema": 2}')
        assert gs.load_or_empty_readonly(path).status == "newer"

    def test_quarantine_moves_a_corrupt_file_aside_with_a_timestamp(self, path: Path) -> None:
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        moved = gs.quarantine_corrupt(path, now="20261102T101500")
        assert moved.name == "guard-state.json.corrupt-20261102T101500"
        assert moved.read_text() == "{broken"
        assert not path.exists()

    def test_quarantine_never_overwrites_an_earlier_one(self, path: Path) -> None:
        path.parent.mkdir(parents=True)
        for i in range(2):
            path.write_text(f"{{broken {i}")
            gs.quarantine_corrupt(path, now="20261102T101500")
        names = sorted(p.name for p in path.parent.iterdir())
        assert len(names) == 2

    def test_quarantine_of_a_missing_file_is_a_no_op(self, path: Path) -> None:
        assert gs.quarantine_corrupt(path, now="x") is None


class TestModuleHygiene:
    def test_no_cli_click_or_jinja_imports_and_small(self) -> None:
        source = Path(gs.__file__).read_text(encoding="utf-8")
        roots = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                roots |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module)
        assert not [r for r in roots if r.split(".")[0] in {"click", "jinja2", "yaml"}]
        assert "carter.cli" not in roots
        assert (
            len(source.splitlines()) < 270
        )  # step 9 asked for < 200; 2a added the repo-hook and consent-offer helpers
