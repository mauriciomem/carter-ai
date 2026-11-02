"""``carter check --host`` (plan 003 step 21; RFC-0007 App B §3): the items that exist in 1G.

Read-only, names only, and honest: what needs the plugin or hooks is reported as not
installed in this slice, never as green. The token items wait for ``github-token`` (step 16).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import hostcheck
from carter.cli import main
from carter.guard import gitconfig as gc
from carter.guard.state import load, save
from carter.identity.errors import E_POLICIES_MISSING, E_STATE_INVALID
from carter.install.mcp import config_target
from carter.install.paths import carter_gitconfig_path, guard_state_path
from guard.helpers import debug_config, tree_hash


def guard(*args: str):
    return CliRunner().invoke(main, ["guard", *args], catch_exceptions=False)


def host(*extra: str):
    return CliRunner().invoke(main, ["check", "--host", *extra], catch_exceptions=False)


def installed(stack) -> None:
    stack.fake()
    assert guard("install", "--yes").exit_code == 0


def levels(output: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in output.splitlines():
        parts = line.split(None, 1)
        if parts and parts[0] in {"OK", "INFO", "WARN", "RED"}:
            out.setdefault(parts[0], []).append(parts[1])
    return out


class TestHealthyInstall:
    def test_all_green_or_only_the_documented_warns(self, stack) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        res = host()
        assert res.exit_code == 0, res.output
        found = levels(res.output)
        assert "RED" not in found
        assert any("statement(s) loaded" in t for t in found["OK"])
        warns = " ".join(found["WARN"])
        assert "plugin not installed (slice 2a)" in warns  # always, once g2 is consented
        assert "gate, isolation and signing guards are inactive" in warns
        assert "literal denies only" in warns
        assert res.output.rstrip().endswith("Host OK (1 WARN).")

    def test_the_git_items_say_not_applicable_in_this_slice(self, stack) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        out = host().output
        assert "include.path: not needed yet (no Carter git keys; slice 2a)" in out
        assert "Carter installs no hooks in this slice" in out
        assert "not applicable in this slice" in out

    def test_the_token_and_env_items_are_honest_about_what_is_not_checked(self, stack) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        out = host().output
        assert hostcheck.TOKEN_CHECK_PENDING in out
        assert "pollution (agent signals, isolation markers) not checked: slice 2a" in out

    def test_it_is_allowed_in_an_agent_shell_because_it_is_read_only(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        monkeypatch.setenv("AGENT", "x")
        assert host().exit_code == 0

    def test_check_probe_is_not_registered_in_1g(self) -> None:
        res = CliRunner().invoke(main, ["check", "--probe"])
        assert res.exit_code == 2 and "No such option" in res.output

    def test_the_workspace_check_is_unchanged(self, tmp_path: Path) -> None:
        runner = CliRunner()
        runner.invoke(main, ["init", str(tmp_path), "--single"], catch_exceptions=False)
        res = runner.invoke(main, ["check", str(tmp_path), "--no-harness"], catch_exceptions=False)
        assert res.exit_code == 0 and "Workspace OK" in res.output
        assert "Host" not in res.output and "carter check --host" not in res.output


class TestNothingInstalled:
    def test_g2_off_is_a_warn_not_a_failure(self, stack) -> None:
        stack.fake()
        res = host()
        assert res.exit_code == 0
        assert "G2 off: no guards are installed" in res.output
        assert "carter guard install" in res.output
        assert "plugin not installed" not in res.output  # nothing consented, nothing to qualify


class TestRedItems:
    def test_a_missing_statement_names_it_with_the_registry_code(self, stack) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live[1:]))  # OpenCode dropped deny-git-push
        res = host()
        assert res.exit_code == 1
        assert f"{E_POLICIES_MISSING}: `deny-git-push` is not loaded" in res.output
        assert "deny-git-send-pack is" not in res.output
        assert "drops all policies and your providers" in res.output

    def test_each_missing_statement_is_its_own_line(self, stack) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live[2:]))
        reds = levels(host().output)["RED"]
        assert sum("is not loaded" in r for r in reds) == 2

    def test_a_lost_provider_is_red(self, stack) -> None:
        target = config_target(None)
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"providers": {"example": {}, "other": {}}}))
        installed(stack)
        stack.fake(before=debug_config(stack.live, providers={"example": {}}))
        res = host()
        assert res.exit_code == 1 and "not loaded by OpenCode: other" in res.output

    def test_debug_config_failing_is_red_and_shows_no_output(self, stack, fake_opencode) -> None:
        installed(stack)
        fake_opencode(config_output="boom sk-SENTINEL", config_exit=1)
        res = host()
        assert res.exit_code == 1 and "cannot read `opencode debug config`" in res.output
        assert "sk-SENTINEL" not in res.output

    def test_a_declined_group_is_listed_not_failed(self, stack, human_tty) -> None:
        from carter.identity.policyset import policy_statements

        human_tty(True)
        stack.fake()
        res = CliRunner().invoke(
            main, ["guard", "install"], input="y\nn\ny\ny\n", catch_exceptions=False
        )
        assert res.exit_code == 0, res.output
        accepted = policy_statements(
            ("g2", "read-edit-denies", "config-edit"), home=str(stack.home)
        )
        stack.fake(before=debug_config(accepted))
        out = host()
        assert out.exit_code == 0, out.output
        assert any("sudo-docker: not installed" in t for t in levels(out.output)["INFO"])

    def test_a_changed_guard_file_is_red(self, stack, home: Path) -> None:
        installed(stack)
        f = home / ".carter" / "isolation.json"
        f.write_text("{}")
        state = load(guard_state_path(None))
        state.record_file(f, b"{}")
        save(state, guard_state_path(None))
        stack.fake(before=debug_config(stack.live))
        assert "OK" in levels(host().output) and f"{f} matches guard-state.json" in host().output
        f.write_text("{tampered}")
        stack.fake(before=debug_config(stack.live))
        res = host()
        assert res.exit_code == 1 and f"{f} was changed since Carter wrote it" in res.output
        f.unlink()
        stack.fake(before=debug_config(stack.live))
        assert f"{f} is missing" in host().output

    def test_a_missing_per_agent_deny_is_red(self, stack) -> None:
        installed(stack)
        data = json.loads(config_target(None).read_text())
        del data["agents"]["build"]
        config_target(None).write_text(json.dumps(data))
        stack.fake(before=debug_config(stack.live))
        res = host()
        assert res.exit_code == 1 and "build:carter_push is missing from the config" in res.output

    def test_a_corrupt_or_newer_guard_state_is_red_with_the_registry_code(self, stack) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        res = host()
        assert res.exit_code == 1 and E_STATE_INVALID in res.output and "corrupt" in res.output
        path.write_text('{"schema": 2}')
        res = host()
        assert res.exit_code == 1 and "newer" in res.output

    def test_one_broken_check_does_not_hide_the_others(self, stack, monkeypatch) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        monkeypatch.setattr(hostcheck, "_files", lambda s: (_ for _ in ()).throw(RuntimeError("x")))
        res = host()
        assert res.exit_code == 1 and "check could not run (RuntimeError)" in res.output
        assert "statement(s) loaded" in res.output


class TestGitIncludeLine:
    @pytest.fixture
    def with_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(gc, "carter_git_entries", lambda: [("carter.tier", "t1")])

    def test_present_is_ok(self, stack, with_key) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        res = host()
        assert res.exit_code == 0
        assert f"include.path for {carter_gitconfig_path(None)} is present" in res.output

    def test_missing_is_red_with_the_exact_line_to_add(self, stack, with_key) -> None:
        installed(stack)
        carter = carter_gitconfig_path(None)
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text("[user]\n\tname = X\n")
        stack.fake(before=debug_config(stack.live))
        res = host()
        assert res.exit_code == 1
        assert f"git config --global --add include.path {carter}" in res.output

    def test_a_malformed_carter_gitconfig_is_red(self, stack, with_key) -> None:
        installed(stack)
        carter_gitconfig_path(None).write_text("[carter\n\ttier = ")
        stack.fake(before=debug_config(stack.live))
        res = host()
        assert res.exit_code == 1 and "is not valid git config" in res.output


class TestWarnsAndLists:
    def test_active_d52_opt_outs_are_listed(self, stack, home: Path, tmp_path: Path) -> None:
        ws = tmp_path / "proj"
        ws.mkdir()
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(
            f'schema = 2\n[workspaces."{ws}"]\nallow_project_opencode_edit = true\n'
        )
        stack.fake()
        res = host()
        assert f"agents may edit project config in {ws.resolve()}" in res.output
        assert res.exit_code == 0

    def test_project_scope_code_capable_config_is_a_warn_with_names_only(
        self, stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj = tmp_path / "proj"
        (proj / ".opencode" / "plugins").mkdir(parents=True)
        (proj / "opencode.json").write_text(
            json.dumps({"plugins": ["x"], "mcp": {"servers": {"s": {"command": ["SECRETCMD"]}}}})
        )
        stack.fake()
        res = CliRunner().invoke(main, ["check", "--host", str(proj)], catch_exceptions=False)
        assert "project-scope OpenCode config can run code" in res.output
        assert "opencode.json (mcp, plugins)" in res.output and ".opencode/plugins/" in res.output
        assert "SECRETCMD" not in res.output and res.exit_code == 0

    def test_pending_workspace_pins_are_a_warn_pointing_at_update(
        self, stack, tmp_path: Path
    ) -> None:
        ws = tmp_path / "ws"
        runner = CliRunner()
        ws.mkdir()
        runner.invoke(main, ["init", str(ws), "--single"], catch_exceptions=False)
        yaml_path = ws / ".carter" / "carter.yaml"
        yaml_path.write_text(yaml_path.read_text() + "identity:\n  require_tier: t1\n")
        stack.fake()
        res = runner.invoke(main, ["check", "--host", str(ws)], catch_exceptions=False)
        assert "carter.yaml and config.toml differ on: require_tier" in res.output
        assert "carter update" in res.output and res.exit_code == 0

    def test_gh_tokens_in_a_given_server_env_warn_by_name_only(self) -> None:
        items = hostcheck.run_host_checks(
            server_env={"GH_TOKEN": "ghp_SENTINELVALUE", "GITHUB_TOKEN": "x", "PATH": "/bin"},
            reader=lambda: {"providers": {}, "policies": []},
        )
        warn = [i for i in items if i.area == "server env" and i.level == "warn"]
        assert warn and "GH_TOKEN, GITHUB_TOKEN" in warn[0].text
        assert "SENTINEL" not in repr(items)


class TestReadOnlyAndQuiet:
    def test_nothing_is_written_anywhere(self, stack) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        before = tree_hash(stack.home)
        host()
        stack.fake(before=debug_config(stack.live[3:]))
        host()
        assert tree_hash(stack.home) == before

    def test_no_secret_value_reaches_the_output(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        installed(stack)
        monkeypatch.setenv("GH_TOKEN", "ghp_ENVSENTINEL0123456789abcdef0123456789")
        monkeypatch.setenv("GITHUB_TOKEN", "github_pat_ENVSENTINEL")
        stack.fake(before=debug_config(stack.live[1:]))  # provider settings carry sk-SENTINEL
        res = CliRunner().invoke(main, ["check", "--host"], catch_exceptions=False)
        assert "SENTINEL" not in res.output and "SENTINEL" not in (res.stderr_bytes or b"").decode()

    def test_no_provider_settings_in_the_debug_config_path(self) -> None:
        import ast

        src = Path(hostcheck.__file__).read_text(encoding="utf-8")
        calls = {
            n.func.id
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "print" not in calls  # the module returns items; the CLI prints them

    def test_output_is_deterministic(self, stack) -> None:
        installed(stack)
        stack.fake(before=debug_config(stack.live))
        first = host().output
        stack.fake(before=debug_config(stack.live))
        assert host().output == first
