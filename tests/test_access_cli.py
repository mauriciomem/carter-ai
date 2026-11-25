"""``carter access``: the read-only view of what agents may do here.

Rows, sources, header variants, the lines for missing consent groups (also in ``carter check``),
the ``-v`` column, the width rule, and that it works, and writes nothing, in an agent shell.
"""

from __future__ import annotations

import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner, Result

from access_support import ALL_GROUPS, record_groups
from carter import accessload
from carter.access import resolve, warnings
from carter.cli import main
from carter.install.paths import guard_state_path

ROW = re.compile(
    r"^\s+(?P<label>.+?)\s+\[(?P<id>[a-z_]+)\]\s+(?P<value>\S+)(?:\s+(?P<source>\S+))?$"
)
NOT_INSTALLED = re.compile(r"^! .* off:")


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    assert CliRunner().invoke(main, ["init", str(path), "--no-git-state"]).exit_code == 0
    monkeypatch.chdir(path)
    return path


def _config(text: str) -> None:
    home = Path.home() / ".carter"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(text, encoding="utf-8")


def _workspace_yaml(ws: Path, extra: str) -> None:
    yml = ws / ".carter" / "carter.yaml"
    yml.write_text(yml.read_text() + extra)


def _access(*args: str, env: dict[str, str] | None = None) -> Result:
    return CliRunner().invoke(main, ["access", *args], env=env or {})


def _rows(result: Result) -> dict[str, tuple[str, str | None]]:
    found = {}
    for line in result.stdout.splitlines():
        match = ROW.match(line)
        if match:
            found[match["id"]] = (match["value"], match["source"])
    return found


class TestRowsAndSources:
    def test_with_no_access_table_the_level_is_strict_by_default(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        result = _access()
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[0] == "Access level: strict  (default)"
        rows = _rows(result)
        assert rows["pr_write"] == ("ask", "preset")
        assert rows["issue_write"] == ("denied", "preset")
        assert rows["destructive"] == ("denied", "preset")
        assert result.stdout.splitlines()[-1] == "see: carter access --help"
        assert result.stderr == ""

    def test_the_level_comes_from_config_toml(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\n')
        result = _access()
        assert result.stdout.splitlines()[0] == "Access level: guarded  (~/.carter/config.toml)"
        assert _rows(result)["pr_write"] == ("allowed", "preset")

    def test_relaxed_opens_only_issue_writes_beyond_guarded(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\n')
        guarded = _rows(_access())
        _config('[access]\nlevel = "relaxed"\n')
        relaxed = _rows(_access())
        assert {k for k in guarded if guarded[k] != relaxed[k]} == {"issue_write"}
        assert relaxed["issue_write"] == ("allowed", "preset")

    def test_an_override_says_so(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\npr_write = "ask"\n')
        assert _rows(_access())["pr_write"] == ("ask", "override")

    def test_a_workspace_that_tightens_a_row_is_named(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\n')
        _workspace_yaml(ws, "access:\n  destructive: denied\n")
        result = _access()
        assert _rows(result)["destructive"] == ("denied", "workspace")
        assert _rows(result)["infra_apply"] == ("ask", "preset")

    def test_a_workspace_level_that_tightens_the_level_is_named_in_the_header(
        self, ws: Path
    ) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\n')
        _workspace_yaml(ws, "access:\n  level: strict\n")
        result = _access()
        assert (
            result.stdout.splitlines()[0] == "Access level: strict  (carter.yaml tightens guarded)"
        )
        assert _rows(result)["pr_write"] == ("ask", "workspace")

    def test_a_looser_workspace_is_ignored_and_the_line_says_so(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _workspace_yaml(ws, "access:\n  pr_write: allowed\n")
        result = _access()
        assert _rows(result)["pr_write"] == ("ask", "preset")
        assert "! carter.yaml access.pr_write ignored: can only harden" in result.stderr

    def test_an_invalid_table_prints_why_and_shows_strict(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\ngitcommit = "ask"\n')
        result = _access()
        assert result.exit_code == 0
        assert result.stdout.splitlines()[0] == "Access level: strict  (config invalid)"
        assert "! config.toml [access]: unknown key 'gitcommit'" in result.stderr
        assert "! access config invalid: using strict" in result.stderr
        assert _rows(result)["pr_write"] == ("ask", "preset")

    def test_a_toml_syntax_error_anywhere_shows_strict(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "relaxed"\n[broken\n')
        result = _access()
        assert result.exit_code == 0
        assert "Access level: strict  (config invalid)" in result.stdout
        assert "! access config invalid: using strict" in result.stderr

    def test_the_project_config_opt_out_is_shown_as_the_source(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config(f'[workspaces."{ws}"]\nallow_project_opencode_edit = true\n')
        assert _rows(_access())["opencode_config"] == ("allowed", "opt-out")

    def test_the_opt_out_needs_the_config_edit_group_and_this_workspace(
        self, ws: Path, tmp_path: Path
    ) -> None:
        _config(f'[workspaces."{ws}"]\nallow_project_opencode_edit = true\n')
        record_groups(*[g for g in ALL_GROUPS if g != "config-edit"])
        assert _rows(_access())["opencode_config"] == ("denied", "preset")
        other = tmp_path / "other"
        other.mkdir()
        record_groups(*ALL_GROUPS)
        _config(f'[workspaces."{other}"]\nallow_project_opencode_edit = true\n')
        assert _rows(_access())["opencode_config"] == ("denied", "preset")

    def test_opencode_config_is_denied_at_every_level(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        for level in ("strict", "guarded", "relaxed"):
            _config(f'[access]\nlevel = "{level}"\n')
            assert _rows(_access())["opencode_config"] == ("denied", "preset")

    def test_destructive_and_infra_never_print_allowed(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        for level in ("strict", "guarded", "relaxed"):
            _config(f'[access]\nlevel = "{level}"\n')
            rows = _rows(_access())
            assert rows["destructive"][0] != "allowed" and rows["infra_apply"][0] != "allowed"

    def test_the_floor_is_never_and_has_no_source(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        rows = _rows(_access())
        for floor_id in ("push", "gh_api", "github_admin", "sudo", "secrets", "carter_internals"):
            assert rows[floor_id] == ("never", None)

    def test_network_and_packages_are_not_rows(self, ws: Path) -> None:
        out = _access("-v").stdout.lower()
        assert "network" not in out and "package" not in out

    def test_it_works_outside_a_workspace(self, tmp_path: Path, monkeypatch) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.chdir(bare)
        _config('[access]\nlevel = "guarded"\n')
        result = _access()
        assert result.exit_code == 0, result.output
        assert _rows(result)["pr_write"] == ("allowed", "preset")

    def test_an_unreadable_carter_yaml_is_the_one_failure(self, ws: Path) -> None:
        """A skipped workspace file would show looser values than apply: exit 1, not a guess."""
        (ws / ".carter" / "carter.yaml").write_text("agents: [unterminated\n")
        result = _access()
        assert result.exit_code == 1
        assert result.stderr.startswith("✗ ") and "Level" not in result.stdout

    def test_it_works_from_a_subfolder_of_the_workspace(self, ws: Path, monkeypatch) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\n')
        _workspace_yaml(ws, "access:\n  destructive: denied\n")
        (ws / "src").mkdir()
        monkeypatch.chdir(ws / "src")
        assert _rows(_access())["destructive"] == ("denied", "workspace")


class TestMissingGroups:
    def test_no_guards_means_one_line_per_group_on_stderr(self, ws: Path) -> None:
        result = _access()
        lines = [ln for ln in result.stderr.splitlines() if NOT_INSTALLED.match(ln)]
        assert lines == [
            "! g2 off: push, gh_api, github_admin, sudo, carter_internals",
            "! read-edit-denies off: secrets",
            "! docker off: agents may run docker (root-equivalent)",
            "! hooks off: agent commits are not checked",
            "! config-edit off: agents can edit this level",
        ]
        assert all(len(ln) <= 60 for ln in lines)
        assert result.exit_code == 0

    def test_a_group_that_is_there_has_no_line(self, ws: Path) -> None:
        record_groups(*[g for g in ALL_GROUPS if g != "g2"])
        assert _access().stderr.splitlines() == [
            "! g2 off: push, gh_api, github_admin, carter_internals"
        ]

    def test_either_commit_hook_group_counts(self, ws: Path) -> None:
        record_groups("g2", "docker", "read-edit-denies", "config-edit", "repo_hooks")
        assert _access().stderr == ""

    def test_all_groups_means_no_line(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        assert _access().stderr == ""

    def test_a_corrupt_state_file_counts_as_none_installed(self, ws: Path) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json")
        assert len(_access().stderr.splitlines()) == 5
        assert path.read_text() == "not json"

    def test_the_floor_rows_still_print_never(self, ws: Path) -> None:
        assert _rows(_access())["push"] == ("never", None)

    def test_check_prints_one_summary_line_and_the_clean_run_prints_none(self, ws: Path) -> None:
        check = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])
        assert check.exit_code == 0, check.output
        assert check.stderr.splitlines() == ["! 5 guard groups missing (see: carter access)"]
        record_groups(*[g for g in ALL_GROUPS if g != "g2"])
        assert CliRunner().invoke(main, ["update", str(ws)]).exit_code == 0
        one = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])
        assert one.stderr.splitlines() == ["! 1 guard group missing (see: carter access)"]
        record_groups(*ALL_GROUPS)
        assert CliRunner().invoke(main, ["update", str(ws)]).exit_code == 0  # render with the rules
        assert CliRunner().invoke(main, ["check", str(ws), "--no-harness"]).stderr == ""

    def test_check_prints_the_access_notes_but_not_the_upgrade_notice(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\ngitcommit = "ask"\n')
        err = CliRunner().invoke(main, ["check", str(ws), "--no-harness"]).stderr
        assert "! config.toml [access]: unknown key 'gitcommit'" in err
        assert err.count("access config invalid: using strict") == 1
        _config("")
        notice = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])
        assert "access level is now strict" not in notice.output

    def test_update_does_not_grow_the_group_lines(self, ws: Path) -> None:
        out = CliRunner().invoke(main, ["update", str(ws)]).output
        assert " off:" not in out and "guard group" not in out


class TestVerboseColumn:
    def test_without_v_there_is_no_enforced_by_text(self, ws: Path) -> None:
        assert "enforced by" not in _access().output

    def test_v_adds_the_layer_and_strength_under_each_row(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        lines = _access("-v").stdout.splitlines()
        assert sum("enforced by" in ln for ln in lines) == 15
        rows = [i for i, ln in enumerate(lines) if ROW.match(ln)]
        assert all("enforced by" in lines[i + 1] for i in rows)
        assert "      enforced by OpenCode edit permission: medium" in lines
        assert "      enforced by command gate: weak" in lines

    def test_the_global_v_works_too(self, ws: Path) -> None:
        assert "enforced by" in CliRunner().invoke(main, ["-v", "access"]).output

    def test_the_token_warnings_are_one_short_line_each(self) -> None:
        lines = warnings(resolve({"level": "guarded"}), token_writes={"pull_requests", "issues"})
        assert lines == (
            "! token can approve PRs: github_admin is text-gated",
            "! token has Issues: write: issue_write is text-gated",
        )
        assert all(len(ln) <= 80 for ln in lines)


class TestWidth:
    @pytest.mark.parametrize("level", ["strict", "guarded", "relaxed"])
    @pytest.mark.parametrize("args", [(), ("-v",)])
    def test_no_line_is_wider_than_80_and_the_status_lines_than_60(
        self, ws: Path, level: str, args: tuple[str, ...]
    ) -> None:
        _config(f'[access]\nlevel = "{level}"\n')  # no guards: every group line prints too
        _workspace_yaml(ws, "access:\n  destructive: denied\n")  # the widest source: `workspace`
        result = _access(*args)
        every = [*result.stdout.splitlines(), *result.stderr.splitlines()]
        assert max(len(ln) for ln in every) <= 80
        status = [ln for ln in every if ln.startswith(("Access level", "!", "see:"))]
        assert status and all(len(ln) <= 60 for ln in status), status


class TestAgentShell:
    def test_it_works_in_an_agent_shell_with_the_same_output(self, ws: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\n')
        human = _access()
        agent = _access(env={"AGENT": "1"})
        assert agent.exit_code == 0, agent.output
        assert agent.output == human.output

    def test_it_writes_nothing(self, ws: Path, tmp_path: Path) -> None:
        record_groups(*ALL_GROUPS)
        _config('[access]\nlevel = "guarded"\n')

        def snapshot() -> dict[str, bytes]:
            roots = (Path.home(), ws)
            return {
                str(p): p.read_bytes() for root in roots for p in root.rglob("*") if p.is_file()
            }

        before = snapshot()
        for args in ((), ("-v",)):
            _access(*args, env={"AGENT": "1"})
        assert snapshot() == before

    def test_it_does_not_record_the_upgrade_notice(self, ws: Path, monkeypatch) -> None:
        monkeypatch.setattr(accessload, "_human_at_terminal", lambda: True)
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"schema": 1}')
        _access()
        assert "access_notice" not in path.read_text()

    def test_it_prints_only_ascii_on_a_stream_that_cannot_show_unicode(self, ws: Path) -> None:
        result = CliRunner(charset="ascii").invoke(main, ["access", "-v"])
        assert result.exit_code == 0, result.output
        assert result.stdout_bytes.isascii() and result.stderr_bytes.isascii()


class TestHelpAndNotice:
    def test_the_notice_points_to_access_help(self) -> None:
        assert accessload.NOTICE == "! access level is now strict (see: carter access --help)"
        assert len(accessload.NOTICE) <= 60

    def test_the_help_epilog_has_the_details(self) -> None:
        out = " ".join(CliRunner().invoke(main, ["access", "--help"]).output.split())
        assert "Show what agents may do here" in out
        assert "~/.carter/config.toml" in out and "allowed, ask, denied" in out
        assert "never" in out and "can only tighten" in out
        assert "guard-state.json" in out and "repeats" in out  # the notice, until it can be kept
        assert "Network and package installs are not limited until a sandbox exists" in out
        assert "-v" in out

    def test_it_takes_no_other_option(self) -> None:
        command = main.get_command(click.Context(main), "access")
        assert command is not None
        assert {opt for param in command.params for opt in param.opts} == {"-v", "--verbose"}
        assert command.params and all(not p.required for p in command.params)

    def test_the_command_is_listed(self) -> None:
        assert "access" in CliRunner().invoke(main, ["--help"]).output
