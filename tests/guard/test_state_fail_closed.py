"""A guard state that cannot be read or trusted never loosens an agent file (fails closed).

Before: the rendered ``permissions:`` lost G2's rules on the next re-render, because an
unreadable ``guard-state.json`` was treated as "nothing installed".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from carter.cli import main
from carter.guard import agent_rules
from carter.guard.state import GuardState, save
from carter.identity.errors import IdentityError
from carter.install import components
from carter.install.paths import guard_state_path

LINE = "guard state unusable: guards kept (see: carter guard --help)"
VALID = json.dumps({"schema": 1, "consents": {"g2": {"decision": "accepted", "rev": 3}}})


def as_set(rules: list[dict[str, str]]) -> set[tuple[str, str, str]]:
    return {(r["action"], r["resource"], r["effect"]) for r in rules}


def denies(rules: list[dict[str, str]]) -> set[tuple[str, str, str]]:
    return {r for r in as_set(rules) if r[2] == "deny"}


def break_it(path: Path, how: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    if how == "corrupt":
        path.write_text("{not json")
    elif how == "truncated":
        path.write_text(VALID[: len(VALID) // 2])
    elif how == "newer":
        path.write_text(json.dumps({"schema": 99}))
    elif how == "wrong-type":
        path.write_text(json.dumps({"schema": 1, "consents": "x"}))
    elif how == "not-an-object":
        path.write_text("[]")
    elif how == "binary":
        path.write_bytes(b"\xff\xfe\x00")
    elif how == "directory":
        path.mkdir()
    elif how == "dangling-symlink":
        path.symlink_to(path.parent / "gone.json")
    elif how == "no-permission":
        path.write_text(VALID)
        path.chmod(0)
    else:
        raise AssertionError(how)


HOWS = [
    "corrupt",
    "truncated",
    "newer",
    "wrong-type",
    "not-an-object",
    "binary",
    "directory",
    "dangling-symlink",
    "no-permission",
]


@pytest.fixture(params=HOWS)
def broken(request: pytest.FixtureRequest, home: Path) -> Path:
    if request.param == "no-permission" and os.geteuid() == 0:
        pytest.skip("root reads any file")
    path = guard_state_path(None)
    break_it(path, request.param)
    yield path
    path.chmod(0o600) if path.is_file() else None


class TestRules:
    def test_never_looser_than_any_valid_state(self, broken: Path, home: Path) -> None:
        got = agent_rules.current_rules(home=str(home))
        every = GuardState()
        for group in ("g2", "docker", "read-edit-denies", "config-edit", "hooks"):
            every.consent(group, "accepted", "2026-01-01", 9)
        assert denies(agent_rules.rules_for(every, home=str(home))) <= denies(got)
        assert ("shell", "git push *", "deny") in as_set(got)

    def test_no_opt_out_is_applied(self, broken: Path, home: Path) -> None:
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(
            f'schema = 2\n[agent_config]\nworkspaces = ["{home}"]\n'
        )
        got = agent_rules.current_rules(home=str(home))
        assert all(r["effect"] == "deny" or r["action"] == "shell" for r in got)
        assert ("edit", f"{home}/.carter/config.toml", "deny") in as_set(got)

    def test_the_file_is_left_alone(self, broken: Path, home: Path) -> None:
        before = os.lstat(broken).st_mode, broken.is_symlink()
        agent_rules.current_rules(home=str(home))
        assert (os.lstat(broken).st_mode, broken.is_symlink()) == before

    def test_it_says_so_once_in_one_short_line(
        self, broken: Path, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent_rules.current_rules(home=str(home))
        agent_rules.current_rules(home=str(home))
        err = capsys.readouterr().err
        assert err.count(LINE) == 1 and len(LINE) <= 60
        assert len(err.splitlines()) == 1

    def test_absent_and_valid_states_are_unchanged(self, home: Path) -> None:
        assert agent_rules.current_rules(home=str(home)) == []
        state = GuardState()
        state.consent("g2", "accepted", "2026-01-01", 3)
        save(state, guard_state_path(None))
        assert ("shell", "git push *", "deny") in as_set(agent_rules.current_rules(home=str(home)))
        got = as_set(agent_rules.current_rules(home=str(home)))
        assert ("shell", "sudo *", "deny") in got  # g2 refuses sudo
        assert ("shell", "docker *", "deny") not in got  # docker waits for its own consent


class TestAgentFiles:
    def agent(self, home: Path) -> dict:
        text = (home / ".config/opencode/agents/carter-engineer.md").read_text()
        return yaml.safe_load(text.split("---", 2)[1])

    def shell(self, front: dict) -> set[tuple[str, str]]:
        rules = front["permissions"]
        return {(r["resource"], r["effect"]) for r in rules if r["action"] == "shell"}

    @pytest.mark.parametrize("how", ["corrupt", "newer", "dangling-symlink"])
    def test_a_re_render_keeps_the_rules_and_the_bad_file(
        self, stack, home: Path, how: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stack.fake()
        res = CliRunner().invoke(main, ["install", "--yes"], catch_exceptions=False)
        assert res.exit_code == 0, res.output
        before = self.shell(self.agent(home))
        assert ("git push *", "deny") in before
        path = guard_state_path(None)
        path.unlink()
        break_it(path, how)
        snapshot = path.read_bytes() if path.is_file() else None
        capsys.readouterr()
        assert components.rerender_agents(None) is not None
        assert before <= self.shell(self.agent(home))  # unchanged or stricter
        assert capsys.readouterr().err.count(LINE) == 1
        assert (path.read_bytes() if path.is_file() else None) == snapshot  # never rewritten

    def test_status_and_check_host_report_it(self, stack, home: Path) -> None:
        break_it(guard_state_path(None), "corrupt")
        status = CliRunner().invoke(main, ["guard", "status"], catch_exceptions=False)
        assert "unusable" in status.output and "installed" not in status.output
        check = CliRunner().invoke(main, ["check", "--host"], catch_exceptions=False)
        assert "E-STATE-INVALID" in check.output


class TestMirrorUpdate:
    @pytest.mark.parametrize("how", ["corrupt", "newer", "dangling-symlink"])
    def test_the_hook_tier_write_does_not_replace_the_bad_file(self, home: Path, how: str) -> None:
        from carter.guard import update_mirror
        from carter.identity import load_identity

        path = guard_state_path(None)
        break_it(path, how)
        snapshot = path.read_bytes() if path.is_file() else None
        with pytest.raises(IdentityError):
            update_mirror.apply(None, load_identity())
        assert (path.read_bytes() if path.is_file() else None) == snapshot
