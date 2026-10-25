"""Harness validation for ``carter check`` (ADR-0014 D6).

``carter check`` runs ``opencode debug agents`` (JSON list on OpenCode 2.1.4) and
verifies every rendered Carter agent was loaded, with its emitted ``permissions:``
present as one in-order block after OpenCode's base rules. Unit tests inject the
runner and sleep (no real waiting); CLI tests use the ``fake_opencode`` script.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import harness
from carter.cli import main

BASE = [
    {"action": "*", "resource": "*", "effect": "allow"},
    {"action": "read", "resource": "*.env", "effect": "ask"},
]
RULES = [
    {"action": "*", "resource": "*", "effect": "ask"},
    {"action": "read", "resource": "~/.carter/*", "effect": "allow"},
]


def _agent(name: str, perms: list[dict] | None = None) -> dict:
    if perms is None:
        expanded = [dict(r, resource=r["resource"].replace("~", "/home/u", 1)) for r in RULES]
        perms = BASE + expanded + [{"action": "browser", "resource": "*", "effect": "deny"}]
    return {"id": name, "name": name, "permissions": perms}


def _proc(stdout: str, code: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["opencode"], code, stdout=stdout, stderr="boom")


class _Runner:
    """Returns queued results in order; repeats the last one."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        item = self.results[min(self.calls, len(self.results)) - 1]
        if isinstance(item, BaseException):
            raise item
        return item


EXPECTED = {"carter-pm-local": RULES, "carter-engineer-local": RULES}


def _validate(runner, sleeps: list | None = None, **kw):
    sleeps = [] if sleeps is None else sleeps
    return harness.validate_agents(
        Path("/ws"),
        EXPECTED,
        runner=runner,
        which=lambda _: "/bin/opencode",
        sleep=sleeps.append,
        home="/home/u",
        **kw,
    )


def _all_present() -> str:
    return json.dumps([_agent("build", BASE), *(_agent(n) for n in EXPECTED)])


class TestValidateAgents:
    def test_all_present_passes(self):
        result = _validate(_Runner(_proc(_all_present())))
        assert result.status == "ok" and result.errors == []

    def test_missing_agent_fails_naming_it(self):
        out = json.dumps([_agent("carter-pm-local")])
        sleeps: list = []
        result = _validate(_Runner(_proc(out)), sleeps)
        assert result.status == "fail"
        assert any("carter-engineer-local" in e and "tools:" in e for e in result.errors)
        assert not any("carter-pm-local" in e for e in result.errors)
        assert len(sleeps) == harness.DEFAULT_ATTEMPTS - 1  # retried, then gave up

    def test_empty_then_populated_retries(self):
        runner = _Runner(_proc("[]"), _proc("[]"), _proc(_all_present()))
        sleeps: list = []
        result = _validate(runner, sleeps)
        assert result.status == "ok"
        assert runner.calls == 3 and len(sleeps) == 2

    def test_always_empty_fails_after_bounded_retries(self):
        runner = _Runner(_proc("[]"))
        sleeps: list = []
        result = _validate(runner, sleeps)
        assert result.status == "fail"
        assert runner.calls == harness.DEFAULT_ATTEMPTS
        assert sum(sleeps) <= 10
        assert any("no agents" in e for e in result.errors)

    def test_attempts_configurable(self):
        runner = _Runner(_proc("[]"))
        _validate(runner, attempts=2)
        assert runner.calls == 2

    def test_garbage_output_fails_cleanly(self):
        result = _validate(_Runner(_proc("Error: not json {")))
        assert result.status == "fail"
        assert any("unparsable" in e for e in result.errors)

    def test_non_list_json_fails_cleanly(self):
        result = _validate(_Runner(_proc('{"a": 1}')))
        assert result.status == "fail"

    def test_nonzero_exit_fails_with_stderr(self):
        result = _validate(_Runner(_proc("", code=3)))
        assert result.status == "fail"
        assert any("exited 3" in e and "boom" in e for e in result.errors)

    def test_timeout_fails_without_retry(self):
        runner = _Runner(subprocess.TimeoutExpired("opencode", 30))
        result = _validate(runner)
        assert result.status == "fail" and runner.calls == 1
        assert any("timed out" in e for e in result.errors)

    def test_runner_gets_timeout_and_cwd(self):
        seen: dict = {}

        def runner(cmd, **kw):
            seen.update(kw, cmd=cmd)
            return _proc(_all_present())

        _validate(runner, timeout=7)
        assert seen["cmd"] == ["/bin/opencode", "debug", "agents"]
        assert seen["timeout"] == 7 and seen["cwd"] == Path("/ws")

    def test_missing_opencode_skips(self):
        result = harness.validate_agents(Path("/ws"), EXPECTED, which=lambda _: None)
        assert result.status == "skipped" and result.errors == []
        assert "opencode" in (result.warning or "")

    def test_permission_drift_fails(self):
        widened = BASE + [{"action": "*", "resource": "*", "effect": "allow"}]
        out = json.dumps([_agent("carter-pm-local", widened), _agent("carter-engineer-local")])
        result = _validate(_Runner(_proc(out)))
        assert result.status == "fail"
        assert any("carter-pm-local" in e and "permissions" in e for e in result.errors)

    def test_rules_must_follow_base_in_order(self):
        reordered = BASE + [
            {"action": "read", "resource": "/home/u/.carter/*", "effect": "allow"},
            {"action": "*", "resource": "*", "effect": "ask"},
        ]
        out = json.dumps([_agent("carter-pm-local", reordered), _agent("carter-engineer-local")])
        assert _validate(_Runner(_proc(out))).status == "fail"

    def test_no_permissions_field_only_checks_presence(self):
        out = json.dumps([{"id": n} for n in EXPECTED])
        assert _validate(_Runner(_proc(out))).status == "ok"


# ─── CLI integration (fake opencode script) ──────────────────────────────────


def _init(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    result = CliRunner().invoke(main, ["init", str(ws), "--no-git-state"])
    assert result.exit_code == 0, result.output
    return ws


def _loaded(ws: Path, drop: str | None = None) -> str:
    import os

    import yaml

    agents = []
    files = sorted((ws / ".opencode" / "agents").glob("*.md"))
    assert files, f"no agents rendered in {ws}"
    for f in files:
        if f.stem == drop:
            continue
        rules = yaml.safe_load(f.read_text().split("---", 2)[1])["permissions"]
        rules = [dict(r, resource=os.path.expanduser(r["resource"])) for r in rules]
        agents.append({"id": f.stem, "permissions": BASE + rules})
    return json.dumps(agents)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(harness.time, "sleep", lambda _s: None)


class TestCheckCli:
    def test_passes_when_all_loaded(self, tmp_path, fake_opencode, no_sleep):
        ws = _init(tmp_path)
        fake_opencode(agents_output=_loaded(ws))
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 0, result.output
        assert "OpenCode loaded" in result.output

    def test_fails_naming_dropped_agent(self, tmp_path, fake_opencode, no_sleep):
        ws = _init(tmp_path)
        fake_opencode(agents_output=_loaded(ws, drop="carter-pm-local"))
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 1
        assert "carter-pm-local" in result.output
        assert "Traceback" not in result.output

    def test_garbage_and_nonzero_fail_cleanly(self, tmp_path, fake_opencode, no_sleep):
        ws = _init(tmp_path)
        fake_opencode(agents_output="garbage", agents_exit=2)
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 1
        assert "exited 2" in result.output
        assert "Traceback" not in result.output

    def test_missing_opencode_warns_and_skips(self, tmp_path, fake_opencode):
        ws = _init(tmp_path)
        fake_opencode(None)
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 0, result.output
        assert "skipping" in result.output.lower() and "Workspace OK" in result.output

    def test_missing_opencode_other_errors_still_fail(self, tmp_path, fake_opencode):
        ws = _init(tmp_path)
        (ws / "AGENTS.md").unlink()
        fake_opencode(None)
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 1
        assert "skipping" in result.output.lower() and "AGENTS.md" in result.output

    def test_no_harness_flag_skips(self, tmp_path, fake_opencode):
        ws = _init(tmp_path)
        fake_opencode(agents_output="garbage", agents_exit=2)
        result = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])
        assert result.exit_code == 0, result.output


class TestCheckWorkspaceFiles:
    """`carter check` file checks that run before the harness step."""

    def test_reports_every_missing_knowledge_file(self, tmp_path):
        from carter.state import KNOWLEDGE_FILES

        ws = _init(tmp_path)
        for name in KNOWLEDGE_FILES:
            (ws / ".carter" / "knowledge" / name).unlink()
        result = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])
        assert result.exit_code == 1
        for name in KNOWLEDGE_FILES:
            assert f"Missing knowledge file: .carter/knowledge/{name}" in result.output

    def test_agent_frontmatter_with_bom_is_parsed(self, tmp_path):
        ws = _init(tmp_path)
        agent = next((ws / ".opencode" / "agents").glob("carter-*.md"))
        agent.write_text("\ufeff" + agent.read_text())
        result = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])
        assert result.exit_code == 0, result.output
        assert "Unparseable frontmatter" not in result.output
