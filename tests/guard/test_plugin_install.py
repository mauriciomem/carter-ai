"""Plugin packaging, render and install (plan 004 step 26; RFC-0007 C.6.2, freeze G2/G3/G4).

Everything under the sandbox HOME with a fake OpenCode; the real server is step 32.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import gitconfig as gc
from carter.guard import plugin
from carter.guard.state import GuardState, load
from carter.identity import isolation
from carter.identity.errors import E_FALSE_MISSING, IdentityError
from carter.identity.isolation_schema import validate
from carter.identity.rules import load_rules
from carter.install.paths import guard_state_path, isolation_path, plugin_dir, run_dir
from guard.helpers import debug_config


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *args], catch_exceptions=False, **kw)


def installed(stack) -> None:
    stack.fake()
    res = guard("install", "--yes")
    assert res.exit_code == 0, res.output


class TestRender:
    def test_the_index_carries_the_hash_of_the_final_isolation_bytes(self, stack) -> None:
        installed(stack)
        iso = isolation_path(None).read_bytes()
        index = (plugin_dir(None) / "index.ts").read_text()
        assert f'"{isolation.sha256_hex(iso)}"' in index
        assert "__CARTER_" not in index
        assert (plugin_dir(None) / "core.ts").read_bytes() == (
            plugin.SOURCE / "core.ts"
        ).read_bytes()

    def test_the_source_in_the_repository_is_unrendered(self) -> None:
        text = (plugin.SOURCE / "index.ts").read_text()
        assert "__CARTER_ISOLATION_SHA256__" in text  # refuses by construction (step 14 tests)

    def test_isolation_json_is_canonical_valid_and_absolute(self, stack) -> None:
        installed(stack)
        raw = isolation_path(None).read_bytes()
        doc = json.loads(raw)
        validate(doc)
        assert raw == isolation.canonical_bytes(doc)
        pl = doc["plugin"]
        assert os.path.isabs(pl["python_path"]) and os.access(pl["python_path"], os.X_OK)
        assert os.path.isabs(pl["carter_path"]) and os.access(pl["carter_path"], os.X_OK)
        assert pl["declined_groups"] == [] and pl["pat_file"].endswith("secrets/gh-read.token")
        assert doc["env"]["set"]["GH_CONFIG_DIR"] == f"{Path.home()}/.carter/run/gh-empty"

    def test_declined_groups_follow_the_state(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        guard("install", input="y\ny\nn\ny\ny\nn\n")  # g2, hooks, sudo-docker=no, ...
        doc = json.loads(isolation_path(None).read_bytes())
        assert doc["plugin"]["declined_groups"] == ["sudo-docker"]


class TestFiles:
    def test_modes_hashes_and_directories(self, stack) -> None:
        installed(stack)
        state = load(guard_state_path(None))
        for path in (
            isolation_path(None),
            plugin_dir(None) / "index.ts",
            plugin_dir(None) / "core.ts",
        ):
            assert state.owned_unchanged(path), path
        assert stat.S_IMODE(isolation_path(None).stat().st_mode) == 0o600
        assert stat.S_IMODE((plugin_dir(None) / "index.ts").stat().st_mode) == 0o644
        for d in (run_dir(None), run_dir(None) / "gh-empty"):
            assert stat.S_IMODE(d.stat().st_mode) == 0o700, d
        assert list((run_dir(None) / "gh-empty").iterdir()) == []

    def test_nothing_is_registered_in_the_opencode_config(self, stack) -> None:
        installed(stack)
        config = (Path.home() / ".config/opencode/opencode.json").read_text()
        assert "plugins/carter" not in config and '"plugin"' not in config

    def test_the_restart_message_is_printed_when_the_plugin_changed(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes")
        assert "plugin installed:" in res.output and "restart the OpenCode server" in res.output

    def test_reinstall_is_a_byte_identical_no_op(self, stack) -> None:
        installed(stack)
        before = {
            p: p.read_bytes()
            for p in (isolation_path(None), plugin_dir(None) / "index.ts", guard_state_path(None))
        }
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes")
        assert res.exit_code == 0 and "plugin up to date" in res.output
        assert before == {p: p.read_bytes() for p in before}

    def test_an_edited_plugin_file_is_kept_and_reported(self, stack) -> None:
        installed(stack)
        index = plugin_dir(None) / "index.ts"
        index.write_text(index.read_text() + "// mine\n")
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes")
        assert index.read_text().endswith("// mine\n")
        assert (
            f"kept your edited {index}" in res.output and "agent shells are refused" in res.output
        )

    def test_the_plugin_dir_is_a_control_path_and_edit_denied(self) -> None:
        assert "~/.config/opencode/plugins/" in load_rules().control_paths


class TestPreconditions:
    def test_no_root_owned_false_stops_the_install_before_any_write(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing(*_a, **_k):
            raise IdentityError(E_FALSE_MISSING)

        monkeypatch.setattr(isolation, "resolve_false", missing)
        stack.fake()
        before = sorted(p for p in Path.home().rglob("*") if p.is_file())
        res = guard("install", "--yes")
        assert res.exit_code == 1 and "no root-owned `false` found" in res.output
        assert sorted(p for p in Path.home().rglob("*") if p.is_file()) == before
        assert not guard_state_path(None).exists()

    def test_a_python_in_a_temporary_directory_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = tmp_path / "bin" / "python"
        fake.parent.mkdir()
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        (fake.parent / "carter").write_text("#!/bin/sh\n")
        (fake.parent / "carter").chmod(0o755)
        monkeypatch.setattr("sys.executable", str(fake))
        with pytest.raises(plugin.PluginInstallError, match="temporary directory"):
            plugin.find_paths()
        assert plugin.find_paths(allow_temp=True) == (str(fake), str(fake.parent / "carter"))

    def test_a_missing_carter_executable_is_an_error(self, tmp_path: Path, monkeypatch) -> None:
        fake = tmp_path / "python"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        monkeypatch.setattr("sys.executable", str(fake))
        monkeypatch.setattr("shutil.which", lambda _n: None)
        with pytest.raises(plugin.PluginInstallError, match="carter"):
            plugin.find_paths(allow_temp=True)


class TestDryRunAndFailure:
    def test_a_dry_run_lists_every_file_and_writes_nothing_even_in_an_agent_shell(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stack.fake()
        monkeypatch.setenv("AGENT", "1")
        before = sorted(p for p in Path.home().rglob("*") if p.is_file())
        res = guard("install", "--dry-run")
        assert res.exit_code == 0, res.output
        for name in (
            "isolation.json",
            "plugins/carter/core.ts",
            "plugins/carter/index.ts",
            "gh-empty",
        ):
            assert name in res.output, name
        assert sorted(p for p in Path.home().rglob("*") if p.is_file()) == before

    def test_a_failure_after_the_config_write_restores_it_and_removes_only_new_files(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stack.fake()
        config = Path.home() / ".config/opencode/opencode.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"keep": true}\n')
        real = gc.install_file

        def flaky(path, content, state, **kw):
            if path.name == "index.ts":
                raise OSError("disk full")
            return real(path, content, state, **kw)

        monkeypatch.setattr(gc, "install_file", flaky)
        with pytest.raises(OSError):
            guard("install", "--yes")
        assert config.read_text() == '{"keep": true}\n'
        assert not isolation_path(None).exists() and not plugin_dir(None).exists()
        assert not guard_state_path(None).exists()


def test_state_without_a_plugin_has_no_plugin_files() -> None:
    assert GuardState().files == []
