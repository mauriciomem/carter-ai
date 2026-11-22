"""Reading `[access]`: the loader, the workspace side, the fail-closed path and the notice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import accessload
from carter.access import UNREADABLE, UserAccess, resolve, resolve_config
from carter.cli import main
from carter.config import generate_default_config, with_user_access
from carter.install.paths import guard_state_path

STRICT_NOTICE = "access level is now strict (see: carter access --help)"


def _write(base: Path, text: str, name: str = "config.toml") -> None:
    (base / "carter").mkdir(parents=True, exist_ok=True)
    (base / "carter" / name).write_text(text, encoding="utf-8")


class TestLoader:
    def test_absent_file_and_absent_table_are_no_access(self, tmp_path):
        assert accessload.load_user_access(tmp_path) == UserAccess()
        _write(tmp_path, "schema = 2\n")
        assert accessload.load_user_access(tmp_path) == UserAccess()

    def test_the_users_table_is_read_as_written(self, tmp_path):
        _write(tmp_path, '[access]\nlevel = "guarded"\npr_write = "ask"\n')
        assert accessload.load_user_access(tmp_path).table == {
            "level": "guarded",
            "pr_write": "ask",
        }

    def test_a_syntax_error_anywhere_fails_closed(self, tmp_path):
        _write(tmp_path, '[access]\nlevel = "guarded"\n[identity\n')
        user = accessload.load_user_access(tmp_path)
        assert user.error == UNREADABLE and user.table is None
        access = resolve(user.table, user_error=user.error)
        assert access.level == "strict" and access.level_source == "fallback"
        assert access.notes == (UNREADABLE, "! access config invalid: using strict")
        assert all(len(line) <= 80 for line in access.notes)

    def test_a_table_that_is_not_a_table_is_passed_on_to_be_refused(self, tmp_path):
        _write(tmp_path, 'access = "guarded"\n')
        assert accessload.load_user_access(tmp_path).table == "guarded"

    def test_the_managed_file_is_not_read(self, tmp_path):
        """Each key has one owning file: `[access]` belongs to config.toml alone."""
        _write(tmp_path, '[access]\nlevel = "relaxed"\n', "config-managed.toml")
        assert accessload.load_user_access(tmp_path) == UserAccess()
        _write(tmp_path, '[access]\nlevel = "guarded"\n')
        assert accessload.load_user_access(tmp_path).table == {"level": "guarded"}

    def test_the_workspace_side_comes_only_from_carter_yaml(self):
        config = generate_default_config()
        config["access"] = {"level": "strict"}
        config["policy"]["level"] = "strict"
        user = UserAccess(table={"level": "relaxed"})
        access = resolve_config(with_user_access(config, user))
        assert (access.level, access.effective_level) == ("relaxed", "strict")
        assert access.notes == ("! carter.yaml policy.level is deprecated: use access.level",)

    def test_without_access_user_the_level_is_strict(self):
        assert resolve_config(generate_default_config()).effective_level == "strict"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    assert CliRunner().invoke(main, ["init", str(path), "--no-git-state"]).exit_code == 0
    return path


@pytest.fixture
def human(monkeypatch):
    """A person at a terminal (the test runner has none)."""
    monkeypatch.setattr(accessload, "_human_at_terminal", lambda: True)


def _update(ws: Path, *args: str, env: dict | None = None):
    return CliRunner().invoke(main, ["update", *args, str(ws)], env=env or {})


def _home_config(text: str) -> None:
    home = Path.home() / ".carter"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(text, encoding="utf-8")


class TestUpgradeNotice:
    def test_it_is_one_short_line(self):
        assert f"! {STRICT_NOTICE}" == accessload.NOTICE
        assert len(accessload.NOTICE) <= 60

    def _a_state_file(self) -> Path:
        """What any machine that ran `carter install` has: a guard state (here, no consents)."""
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1}))
        return path

    def test_shown_once_to_a_human_then_never_again(self, ws, human):
        path = self._a_state_file()
        first = _update(ws)
        assert first.exit_code == 0, first.output
        assert STRICT_NOTICE in first.output
        assert json.loads(path.read_text())["access_notice"]["level"] == "strict"
        assert STRICT_NOTICE not in _update(ws).output

    def test_it_never_creates_the_guard_state(self, ws, human):
        """A machine without guards must keep reporting "none is installed"."""
        from carter.guard.state import load_or_empty_readonly

        assert STRICT_NOTICE in _update(ws).output
        assert not guard_state_path(None).exists()
        assert load_or_empty_readonly(guard_state_path(None)).status == "absent"
        host = CliRunner().invoke(main, ["check", "--host", str(ws)]).output
        assert "the guards are off: none is installed" in host
        assert STRICT_NOTICE in _update(ws).output  # nothing to record it in: it keeps showing

    def test_a_non_tty_run_shows_it_but_does_not_count(self, ws):
        assert STRICT_NOTICE in _update(ws).output
        assert STRICT_NOTICE in _update(ws).output
        assert not guard_state_path(None).exists()

    def test_an_agent_shell_cannot_silence_it(self, ws, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
        out = _update(ws, env={"AGENT": "1"}).output
        assert STRICT_NOTICE in out
        assert not guard_state_path(None).exists()
        assert STRICT_NOTICE in _update(ws, env={"AGENT": "1"}).output

    def test_a_dry_run_does_not_count(self, ws, human):
        assert STRICT_NOTICE in _update(ws, "--dry-run").output
        assert not guard_state_path(None).exists()

    def test_no_notice_when_the_human_set_a_level(self, ws, human):
        _home_config('schema = 2\n[access]\nlevel = "guarded"\n')
        assert STRICT_NOTICE not in _update(ws).output
        assert not guard_state_path(None).exists()

    def test_other_state_is_kept_when_the_notice_is_recorded(self, ws, human):
        path = self._a_state_file()
        path.write_text(json.dumps({"schema": 1, "guard_version": "9.9.9", "future": [1]}))
        _update(ws)
        data = json.loads(path.read_text())
        assert data["guard_version"] == "9.9.9" and data["future"] == [1]
        assert "access_notice" in data

    def test_a_corrupt_state_file_is_not_overwritten_and_the_notice_keeps_showing(self, ws, human):
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json")
        assert STRICT_NOTICE in _update(ws).output
        assert path.read_text() == "not json"
        assert STRICT_NOTICE in _update(ws).output


class TestUpdateReportsTheAccessLines:
    def test_a_bad_access_table_says_so_once_and_renders_strict(self, ws):
        _home_config('schema = 2\n[access]\nlevel = "guarded"\ngitcommit = "ask"\n')
        result = _update(ws)
        assert result.exit_code == 0, result.output
        lines = [ln for ln in result.output.splitlines() if "access" in ln]
        assert "config.toml [access]: unknown key 'gitcommit'" in result.output
        assert result.output.count("access config invalid: using strict") == 1
        assert all(len(ln) <= 80 for ln in lines)
        assert STRICT_NOTICE not in result.output  # a broken table is not an absent one

    def test_a_looser_workspace_is_named_and_ignored(self, ws):
        _home_config('schema = 2\n[access]\nlevel = "strict"\n')
        yml = ws / ".carter" / "carter.yaml"
        yml.write_text(yml.read_text() + "access:\n  pr_write: allowed\n")
        assert "carter.yaml access.pr_write ignored: can only harden" in _update(ws).output

    def test_a_syntax_error_in_the_config_renders_strict(self, ws):
        _home_config('[access]\nlevel = "relaxed"\n[broken\n')
        result = _update(ws)
        assert result.exit_code == 0, result.output
        assert UNREADABLE in result.output
        agent = (ws / ".opencode" / "agents" / "carter-engineer-local.md").read_text()
        assert "gh issue create *" in agent  # rendered; the strict denies are in it


class TestGlobalAgentsFollowTheLevel:
    @pytest.fixture
    def installed(self, fake_opencode) -> Path:
        """Global agents installed with a manifest but no guards (none accepted)."""
        from carter.guard.agent_rules import current_rules
        from carter.install import components, orchestrator

        fake_opencode()
        orchestrator.run(base_dir=None, verbosity=0, guards=False)
        assert components.read_manifest(None) is not None and current_rules() == []
        return Path.home() / ".config" / "opencode" / "agents" / "carter-engineer.md"

    def test_update_refreshes_the_global_agents_with_a_manifest_and_no_guards(self, ws, installed):
        strict_text = installed.read_text()
        _home_config('schema = 2\n[access]\nlevel = "relaxed"\n')
        result = _update(ws)
        assert "global Carter agents refreshed" in result.output
        assert installed.read_text() != strict_text

    def test_an_agent_shell_refreshes_nothing_and_says_so_only_when_something_differs(
        self, ws, installed
    ):
        agent = {"AGENT": "1"}
        assert "not refreshed" not in _update(ws, env=agent).output  # nothing differs yet
        before = installed.read_text()
        _home_config('schema = 2\n[access]\nlevel = "relaxed"\n')
        out = _update(ws, env=agent).output
        assert "global Carter agents not refreshed: agent shells never change them" in out
        assert installed.read_text() == before

    def test_without_a_manifest_update_creates_nothing(self, ws):
        _home_config('schema = 2\n[access]\nlevel = "relaxed"\n')
        _update(ws)
        assert not (Path.home() / ".config" / "opencode" / "agents").exists()
