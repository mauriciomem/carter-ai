"""Harness validation for ``carter check``.

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


def _validate(runner, sleeps: list | None = None, expected=None, **kw):
    sleeps = [] if sleeps is None else sleeps
    return harness.validate_agents(
        Path("/ws"),
        EXPECTED if expected is None else expected,
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
        assert any(
            "carter-engineer-local" in e and "not loaded by OpenCode" in e for e in result.errors
        )
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
        assert seen["cmd"] == ["/bin/opencode", "debug", "agents"]  # no --standalone flag
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

    def test_stale_description_then_fresh_retries(self):
        exp = {n: harness.Expected(RULES, description="New") for n in EXPECTED}
        stale = json.dumps([dict(_agent(n), description="Old") for n in EXPECTED])
        fresh = json.dumps([dict(_agent(n), description="New") for n in EXPECTED])
        runner = _Runner(_proc(stale), _proc(fresh))
        sleeps: list = []
        result = _validate(runner, sleeps, expected=exp)
        assert result.status == "ok", result.errors
        assert runner.calls == 2 and len(sleeps) == 1

    def test_persistent_stale_fails_with_hint(self):
        exp = {n: harness.Expected(RULES, description="New") for n in EXPECTED}
        stale = json.dumps([dict(_agent(n), description="Old") for n in EXPECTED])
        runner = _Runner(_proc(stale))
        result = _validate(runner, expected=exp)
        assert result.status == "fail"
        assert runner.calls == harness.DEFAULT_ATTEMPTS
        assert any("carter-pm-local" in e and "description" in e for e in result.errors)
        assert any("stale" in e and "re-run" in e for e in result.errors)

    def test_missing_only_has_no_stale_hint(self):
        out = json.dumps([_agent("carter-pm-local")])
        result = _validate(_Runner(_proc(out)))
        assert result.status == "fail"
        assert any("carter-engineer-local" in e and "not loaded" in e for e in result.errors)
        assert not any("stale" in e for e in result.errors)

    def test_mismatch_only_has_stale_hint(self):
        exp = {n: harness.Expected(RULES, description="New") for n in EXPECTED}
        out = json.dumps([dict(_agent(n), description="Old") for n in EXPECTED])
        result = _validate(_Runner(_proc(out)), expected=exp)
        assert result.errors[-1].startswith(harness.STALE_HINT.split(";")[0])
        assert not any("not loaded" in e for e in result.errors)

    def test_mixed_reports_both_groups(self):
        exp = {n: harness.Expected(RULES, description="New") for n in EXPECTED}
        out = json.dumps([dict(_agent("carter-pm-local"), description="Old")])
        errors = _validate(_Runner(_proc(out)), expected=exp).errors
        assert len(errors) == 3
        assert "carter-engineer-local" in errors[0] and "not loaded" in errors[0]
        assert "carter-pm-local" in errors[1] and "description" in errors[1]
        assert "stale" in errors[2] and "carter-pm-local" in errors[2]
        assert "carter-engineer-local" not in errors[2]

    def test_stale_model_then_fresh_retries(self):
        exp = {n: harness.Expected(None, model="anthropic/claude-opus-5-5#high") for n in EXPECTED}
        old = {"id": "claude-sonnet-5-5", "providerID": "anthropic"}
        new = {"id": "claude-opus-5-5", "providerID": "anthropic", "variant": "high"}
        runner = _Runner(
            _proc(json.dumps([{"id": n, "model": old} for n in EXPECTED])),
            _proc(json.dumps([{"id": n, "model": new} for n in EXPECTED])),
        )
        assert _validate(runner, expected=exp).status == "ok"
        assert runner.calls == 2

    def test_model_mismatch_names_agent(self):
        exp = {n: harness.Expected(None, model="anthropic/claude-opus-5-5") for n in EXPECTED}
        out = json.dumps([{"id": n, "model": {"id": "x", "providerID": "y"}} for n in EXPECTED])
        result = _validate(_Runner(_proc(out)), expected=exp)
        assert result.status == "fail"
        assert any("carter-pm-local" in e and "model" in e for e in result.errors)

    def test_permission_drift_then_fresh_retries(self):
        widened = BASE + [{"action": "*", "resource": "*", "effect": "allow"}]
        stale = json.dumps([_agent(n, widened) for n in EXPECTED])
        runner = _Runner(_proc(stale), _proc(_all_present()))
        assert _validate(runner).status == "ok" and runner.calls == 2

    def test_waits_for_recent_edits_to_settle(self):
        sleeps: list = []
        runner = _Runner(_proc(_all_present()))
        _validate(runner, sleeps, newest_change=99.5, clock=lambda: 100.0, settle=2.0)
        assert sleeps == [1.5]

    def test_no_settle_wait_for_old_files(self):
        sleeps: list = []
        _validate(_Runner(_proc(_all_present())), sleeps, newest_change=10.0, clock=lambda: 100.0)
        assert sleeps == []

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


def _loaded(ws: Path, drop: str | None = None, stale_description: bool = False) -> str:
    import os

    import yaml

    agents = []
    files = sorted((ws / ".opencode" / "agents").glob("*.md"))
    assert files, f"no agents rendered in {ws}"
    for f in files:
        if f.stem == drop:
            continue
        meta = yaml.safe_load(f.read_text().split("---", 2)[1])
        rules = [dict(r, resource=os.path.expanduser(r["resource"])) for r in meta["permissions"]]
        provider, _, rest = str(meta["model"]).partition("/")
        model_id, _, variant = rest.partition("#")
        model = {"id": model_id, "providerID": provider} | ({"variant": variant} if variant else {})
        if stale_description:
            meta["description"] = "stale " + str(meta.get("description"))
        agents.append(
            {
                "id": f.stem,
                "description": meta.get("description"),
                "model": model,
                "permissions": BASE + rules,
            }
        )
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
        assert "loaded by OpenCode" in result.output

    def test_fails_naming_dropped_agent(self, tmp_path, fake_opencode, no_sleep):
        ws = _init(tmp_path)
        fake_opencode(agents_output=_loaded(ws, drop="carter-pm-local"))
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 1
        assert "carter-pm-local" in result.output
        assert "Traceback" not in result.output

    def test_stale_then_fresh_passes(self, tmp_path, fake_opencode, no_sleep):
        ws = _init(tmp_path)
        fake_opencode(agents_sequence=[_loaded(ws, stale_description=True), _loaded(ws)])
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "fakebin" / "agents.calls").read_text().strip() == "2"

    def test_persistently_stale_description_fails(self, tmp_path, fake_opencode, no_sleep):
        ws = _init(tmp_path)
        fake_opencode(agents_output=_loaded(ws, stale_description=True))
        result = CliRunner().invoke(main, ["check", str(ws)])
        assert result.exit_code == 1
        assert "description" in result.output and "stale" in result.output

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


# --- `opencode debug config` reader (plan 003 step 10; RFC-0007 App C.6.3 step 4) ---------

SENTINEL = "sk-SENTINEL-provider-key-0123456789"
DEBUG_CONFIG = {
    "providers": {"anthropic": {"settings": {"apiKey": SENTINEL}}, "openai": {}},
    "policies": [{"action": "tool.use", "resource": "shell:sudo *", "effect": "deny"}],
}


class TestReadDebugConfig:
    def test_runs_debug_config_in_home_and_parses_json(self, tmp_path: Path) -> None:
        calls: list[tuple] = []

        def runner(argv, **kw):
            calls.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(DEBUG_CONFIG), stderr="")

        got = harness.read_debug_config(
            runner=runner, which=lambda _c: "/x/opencode", home=tmp_path
        )
        assert got == DEBUG_CONFIG
        argv, kw = calls[0]
        assert argv == ["/x/opencode", "debug", "config"]
        assert kw["cwd"] == tmp_path
        assert kw["stdin"] == subprocess.DEVNULL and kw["text"] is True

    def test_cwd_defaults_to_the_home_directory(self) -> None:
        seen = {}

        def runner(argv, **kw):
            seen.update(kw)
            return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

        harness.read_debug_config(runner=runner, which=lambda _c: "/x/opencode")
        assert seen["cwd"] == Path.home()

    @pytest.mark.parametrize("stdout", ["", "not json", "[1, 2]", '"text"', "null"])
    def test_garbage_is_a_typed_error(self, stdout: str) -> None:
        def runner(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        with pytest.raises(harness.DebugConfigError):
            harness.read_debug_config(runner=runner, which=lambda _c: "/x/opencode")

    def test_nonzero_exit_is_a_typed_error(self) -> None:
        def runner(argv, **kw):
            return subprocess.CompletedProcess(argv, 3, stdout=json.dumps(DEBUG_CONFIG), stderr="x")

        with pytest.raises(harness.DebugConfigError, match="exited 3"):
            harness.read_debug_config(runner=runner, which=lambda _c: "/x/opencode")

    def test_timeout_is_a_typed_error(self) -> None:
        def runner(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 1)

        with pytest.raises(harness.DebugConfigError, match="timed out"):
            harness.read_debug_config(runner=runner, which=lambda _c: "/x/opencode", timeout=1)

    def test_missing_opencode_is_a_typed_error(self) -> None:
        with pytest.raises(harness.DebugConfigError, match="not found"):
            harness.read_debug_config(which=lambda _c: None)

    def test_oserror_is_a_typed_error(self) -> None:
        def runner(argv, **kw):
            raise PermissionError("nope")

        with pytest.raises(harness.DebugConfigError):
            harness.read_debug_config(runner=runner, which=lambda _c: "/x/opencode")

    def test_the_text_never_reaches_logs_or_error_messages(
        self, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        caplog.set_level("DEBUG")
        for stdout, code in ((json.dumps(DEBUG_CONFIG), 0), (json.dumps(DEBUG_CONFIG) + "{", 0),
                             (json.dumps(DEBUG_CONFIG), 1)):  # fmt: skip

            def runner(argv, _o=stdout, _c=code, **kw):
                return subprocess.CompletedProcess(argv, _c, stdout=_o, stderr=SENTINEL)

            try:
                harness.read_debug_config(runner=runner, which=lambda _c: "/x/opencode")
            except harness.DebugConfigError as exc:
                assert SENTINEL not in str(exc)
        out = capsys.readouterr()
        assert SENTINEL not in caplog.text + out.out + out.err

    def test_works_against_fake_opencode(self, fake_opencode) -> None:
        fake_opencode(config_output=json.dumps(DEBUG_CONFIG))
        assert harness.read_debug_config() == DEBUG_CONFIG

    def test_fake_opencode_failure_is_typed(self, fake_opencode) -> None:
        fake_opencode(config_output="boom", config_exit=3)
        with pytest.raises(harness.DebugConfigError):
            harness.read_debug_config()

    def test_provider_ids_and_statements_helpers(self) -> None:
        assert harness.provider_ids(DEBUG_CONFIG) == {"anthropic", "openai"}
        assert harness.provider_ids({"provider": {"acme": {}}}) == set()  # D70: only `providers`
        assert harness.provider_ids({}) == set()
        assert harness.policy_statements(DEBUG_CONFIG) == [
            {"action": "tool.use", "resource": "shell:sudo *", "effect": "deny"}
        ]
        old = {"experimental": {"policies": [{"action": "a", "resource": "r", "effect": "deny"}]}}
        assert harness.policy_statements(old) == []  # D70: the older spelling is not read
        assert harness.policy_statements({"policies": "junk"}) == []
