# ruff: noqa: E501
"""Spikes A and B of plan 007 (steps 2-3): plugin tools, the forced ask, latency and timeouts.

Opt-in (``CARTER_E2E=1``), OpenCode 2.1.4 (2.1.2 through ``CARTER_E2E_OPENCODE_ALT``). A real
OpenCode in its own HOME and ports, the mock model, loopback-only netns. The probe plugin
(``probes/broker_probe.ts``) registers stand-ins for ``carter_push`` and a code-mode probe that run
nothing; it records what the tool context carries and how the approval behaves. No credentials,
no git, no real GitHub. Findings: ``.carter/state/plans/active/007-slice-b-broker/notes.md``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from e2e.g2 import CARTER
from e2e.harness import Rig

pytestmark = pytest.mark.e2e

PROBE = (Path(__file__).parent / "probes" / "broker_probe.ts").read_text()
ALLOW_ALL = [{"action": "*", "resource": "*", "effect": "allow"}]
DENY_B = [
    {"action": "carter_push", "resource": "*", "effect": "deny"},
]
AGENTS = {
    "dev": {"mode": "primary", "permissions": ALLOW_ALL},
    "den": {"mode": "primary", "permissions": [*ALLOW_ALL, *DENY_B]},
}
FORCE = 'FORCE carter_push {"note": "n"}'


def force(tool: str = "carter_push", **fields: Any) -> str:
    return f"FORCE {tool} {json.dumps(fields)}"


_BINARY: list[Any] = [None]


@pytest.fixture(autouse=True)
def _binary(opencode_bin: Any) -> None:
    """Run every scenario on the primary binary and, when CARTER_E2E_OPENCODE_ALT is set, on it too."""
    _BINARY[0] = opencode_bin


def make(rig_factory: Callable[..., Rig], **kw: Any) -> Rig:
    extra = {"agents": AGENTS, **kw.pop("extra_config", {})}
    return rig_factory(opencode=_BINARY[0], plugins={"bp": PROBE}, extra_config=extra, **kw)


def log(rig: Rig) -> list[dict[str, Any]]:
    path = rig.logs / "broker-probe.log"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def events(rig: Rig, name: str, since: int = 0) -> list[dict[str, Any]]:
    return [e for e in log(rig)[since:] if e["ev"] == name]


def session(rig: Rig, agent: str) -> str:
    return str(rig.api("POST", "/api/session", {"agent": agent})["data"]["id"])


def pending(rig: Rig) -> list[dict[str, Any]]:
    return list(rig.api("GET", "/api/permission/request")["data"])


def wait_pending(rig: Rig, timeout: float = 15.0, poll: float = 0.02) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = pending(rig)
        if got:
            return got[0]
        time.sleep(poll)
    raise AssertionError("no pending permission request")


def reply(rig: Rig, request: dict[str, Any], decision: str, message: str | None = None) -> None:
    body: dict[str, Any] = {"decision": decision}
    if message:
        body["message"] = message
    rig.api("POST", f"/api/session/{request['sessionID']}/permission/{request['id']}/reply", body)


def wait_for(cond: Callable[[], Any], timeout: float = 15.0, poll: float = 0.05) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = cond()
        if got:
            return got
        time.sleep(poll)
    raise AssertionError("condition not met in time")


def run_prompt(rig: Rig, agent: str, prompt: str) -> str:
    sid = session(rig, agent)
    rig.prompt(sid, prompt)
    return sid


def last_result(rig: Rig, before: int, timeout: float = 15.0) -> str:
    return str(rig.wait_results(before + 1, timeout)[before]["result"])


def reset_logs(rig: Rig) -> None:
    for name in ("broker-probe.log",):
        (rig.logs / name).unlink(missing_ok=True)


# --- A: registration and caller --------------------------------------------------------------


class TestSpikeARegistration:
    def test_tool_context_and_agent_identity(self, rig_factory: Callable[..., Rig]) -> None:
        rig = make(rig_factory)
        setup = events(rig, "setup")[0]
        print(
            "\nA1 ctx keys:",
            setup["ctx_keys"],
            "\n   permission:",
            setup["permission_keys"],
            "\n   tool:",
            setup["tool_keys"],
        )
        run_prompt(rig, "dev", force(mode="noassert"))
        rig.wait_results(1)
        ex = events(rig, "tool.execute")[0]
        print(
            "A1 tool ctx keys:",
            ex["ctx_keys"],
            "agent=",
            ex["agent"],
            ex["agent_type"],
            "signal=",
            ex["has_signal"],
        )
        assert ex["agent"] == "dev" and ex["agent_type"] == "string"
        before = events(rig, "execute.before")[0]
        assert before["agent"] == "dev"
        # a built-in primary, a subagent that reports its own agent
        run_prompt(rig, "build", force(mode="noassert"))
        rig.wait_results(2)
        run_prompt(rig, "build", "TASK " + force(mode="noassert"))
        rig.wait_results(4)
        agents = [e["agent"] for e in events(rig, "tool.execute")]
        print("A1 agents seen by the tool:", agents)
        assert agents[1] == "build" and agents[-1] == "general"
        assert before["session"] != events(rig, "tool.execute")[-1]["session"]

    def test_per_agent_deny_hides_the_tool_and_the_hook_never_runs(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        sid = run_prompt(rig, "den", FORCE)
        text = last_result(rig, 0)
        print("\nA2 denied agent result:", text)
        assert "No tool named" in text
        assert events(rig, "tool.execute") == [] and events(rig, "evaluate") == []
        tools = [
            json.loads(x)["tools"] for x in (rig.logs / "requests.jsonl").read_text().splitlines()
        ]
        names = {n for ts in tools for n in (ts or [])}
        print("A2 tools offered to a denied agent:", sorted(names))
        assert "carter_push" not in names and "carter_probe_cm" not in names
        assert sid

    def test_codemode_flag_decides_where_the_tool_is_listed(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        run_prompt(rig, "dev", "hello")
        time.sleep(2.5)
        requests = [json.loads(x) for x in (rig.logs / "requests.jsonl").read_text().splitlines()]
        names = next(r["tools"] for r in requests if r["tools"])
        print("\nA3 offered to dev:", names)
        assert "carter_push" in names  # codemode false: a direct tool
        assert (
            "carter_probe_cm" not in names
        )  # codemode true: reachable only inside the `execute` tool
        schema = (rig.logs / "tools.json").read_text() if (rig.logs / "tools.json").exists() else ""
        print(
            "A3 execute tool present:",
            "execute" in names,
            "| carter_probe_cm in the first request's tool schemas:",
            "carter_probe_cm" in schema,
        )
        run_prompt(rig, "den", "hello")
        time.sleep(2.5)
        denied = [json.loads(x) for x in (rig.logs / "requests.jsonl").read_text().splitlines()][
            -2:
        ]
        print("A3 denied agent tools:", [r["tools"] for r in denied])
        assert not [n for r in denied for n in r["tools"] if n.startswith("carter_")]

    def test_a_codemode_true_tool_is_callable_through_execute_with_the_callers_agent(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        code = "return Object.keys(tools).filter(k => k.includes('carter'))"
        run_prompt(rig, "dev", f"FORCE execute {json.dumps({'code': code})}")
        first = last_result(rig, 0)
        print("\nA3b execute catalog as dev:", first[:300])
        run_prompt(rig, "den", f"FORCE execute {json.dumps({'code': code})}")
        second = last_result(rig, 1)
        print("A3b execute catalog as denied agent:", second[:300])

    def test_registration_follows_the_status_file_and_reload_does_not_duplicate(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        run_prompt(rig, "dev", 'FORCE bp_ctl {"op": "list"}')
        assert "carter_push" in last_result(rig, 0)
        (rig.logs / "b-status.json").write_text('{"selftest": "failed"}')
        run_prompt(rig, "dev", 'FORCE bp_ctl {"op": "reload"}')
        rig.wait_results(2)
        wait_for(lambda: events(rig, "reloaded"))
        run_prompt(rig, "dev", 'FORCE bp_ctl {"op": "list"}')
        listed = last_result(rig, 2)
        print("\nA4 after status=failed + reload, tools:", listed)
        assert "carter_push" not in listed and "bp_ctl" in listed
        (rig.logs / "b-status.json").write_text('{"selftest": "passed"}')
        run_prompt(rig, "dev", 'FORCE bp_ctl {"op": "reload"}')
        rig.wait_results(4)
        wait_for(lambda: len(events(rig, "reloaded")) == 2)
        run_prompt(rig, "dev", 'FORCE bp_ctl {"op": "list"}')
        listed = last_result(rig, 4)
        print("A4 after status=passed + reload:", listed)
        assert json.loads(listed).count("carter_push") == 1
        # the denied agent still gets nothing while the tool is registered
        run_prompt(rig, "den", FORCE)
        assert "No tool named" in last_result(rig, 5)
        transforms = events(rig, "transform")
        print("A4 transform calls:", [(e["n"], e["status"], e["before"]) for e in transforms])
        assert all(e["before"] == [] for e in transforms), (
            "a transform sees a fresh registry, never the previous tools"
        )

    def test_editing_the_plugin_while_running_reloads_it_without_a_double_registration(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        plugin = rig.config_file.parent / "plugins" / "bp" / "index.ts"
        n_setup = len(events(rig, "setup"))
        plugin.write_text(plugin.read_text() + "\n// touched\n")
        wait_for(lambda: len(events(rig, "setup")) > n_setup)
        time.sleep(1.0)
        run_prompt(rig, "dev", 'FORCE bp_ctl {"op": "list"}')
        listed = json.loads(last_result(rig, 0))
        print("\nA5 after hot reload:", listed, "setups:", len(events(rig, "setup")))
        assert listed.count("carter_push") == 1
        run_prompt(rig, "dev", force(mode="noassert"))
        assert "noassert" in last_result(rig, 1)

    @pytest.mark.parametrize(
        "resource", ["carter_push", "carter_push:*", "carter_*", "carter_*:*", "*:*"]
    )
    def test_a_global_tool_use_policy_vs_a_plugin_tool(
        self, rig_factory: Callable[..., Rig], resource: str
    ) -> None:
        rig = make(
            rig_factory,
            extra_config={
                "policies": [{"action": "tool.use", "resource": resource, "effect": "deny"}]
            },
        )
        run_prompt(rig, "dev", force(mode="noassert"))
        text = last_result(rig, 0)
        print(f"\nA6 policy tool.use {resource!r} deny -> dev result: {text[:120]}")
        # finding: a global `tool.use` policy does not match a plugin-defined tool at all
        assert "noassert" in text and events(rig, "tool.execute")


# --- B: the approval flow -------------------------------------------------------------------


class TestSpikeBApproval:
    def test_assert_without_save_is_always_asked_and_the_hook_forces_ask_for_allow_all(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        sid = run_prompt(rig, "dev", force(note="first"))
        req = wait_pending(rig)
        print(
            "\nB1 pending request:",
            json.dumps(
                {
                    k: req.get(k)
                    for k in ("action", "resources", "save", "metadata", "source", "message")
                }
            ),
        )
        assert req["action"] == "carter_push" and not req.get("save")
        ev = events(rig, "evaluate")[0]
        print("B1 evaluate:", ev["effect_in"], "->", "ask", "keys", ev["keys"])
        assert ev["effect_in"] == "allow" and ev["forced"]
        reply(rig, req, "always")  # no `save`: "always" saves nothing
        assert "carter_push ran after" in last_result(rig, 0)
        run_prompt(rig, "dev", force(note="second"))
        second = wait_pending(rig)
        assert second["id"] != req["id"]
        saved = rig.api("GET", "/api/permission/saved")
        print("B1 saved permissions after 'always':", saved)
        reply(rig, second, "reject")
        wait_for(lambda: len(events(rig, "assert.settled")) == 2)
        assert events(rig, "assert.settled")[-1]["tag"] == "Permission.DeclinedError"
        print(
            "B1 plain reject: settled",
            [(e["ok"], e.get("tag"), e.get("msg")) for e in events(rig, "assert.settled")][-1],
            "| model results so far:",
            len(rig.results()),
        )
        assert sid

    def test_reject_with_and_without_a_message(self, rig_factory: Callable[..., Rig]) -> None:
        rig = make(rig_factory)
        sid = run_prompt(rig, "dev", force())
        reply(rig, wait_pending(rig), "reject")
        wait_for(lambda: events(rig, "assert.settled"))
        time.sleep(1.5)
        plain = events(rig, "assert.settled")[0]
        info = rig.api("GET", f"/api/session/{sid}")["data"]
        print(
            "\nB2 plain reject: tool sees",
            plain.get("tag"),
            plain.get("msg"),
            "| model got a result:",
            len(rig.results()),
            "| session outcome:",
            info.get("outcome"),
            info.get("state"),
        )
        run_prompt(rig, "dev", force())
        reply(rig, wait_pending(rig), "reject", "no thanks")
        text = last_result(rig, len(rig.results()))
        settled = events(rig, "assert.settled")[1]
        print(
            "B2 reject+message: tool sees",
            settled.get("tag"),
            settled.get("msg"),
            "| model text:",
            text[:240],
        )
        assert plain["ok"] is False and settled["ok"] is False

    def test_dwell_of_scripted_replies(self, rig_factory: Callable[..., Rig]) -> None:
        rig = make(rig_factory)
        rows = []
        for delay in (0.0, 0.0, 0.0, 0.25, 0.25, 0.25):
            before = len(events(rig, "assert.ok"))
            run_prompt(rig, "dev", force())
            req = wait_pending(rig, poll=0.005)
            time.sleep(delay)
            reply(rig, req, "once")
            wait_for(lambda n=before: len(events(rig, "assert.ok")) > n)
            rows.append((delay, events(rig, "assert.ok")[-1]["dwell_ms"]))
        print("\nB3 scripted API replies (delay s, dwell ms):", rows)
        assert all(ms >= 0 for _, ms in rows)

    def test_the_dwell_floor_refuses_before_anything_runs(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        run_prompt(rig, "dev", force(min_dwell_ms=200))
        req = wait_pending(rig, poll=0.005)
        reply(rig, req, "once")  # immediately
        text = last_result(rig, 0)
        print("\nB3b fast reply under a 200 ms floor:", text[:200])
        assert "refused" in text

    def test_timeout_leaves_the_request_pending_and_a_late_reply_does_nothing(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        run_prompt(rig, "dev", force(timeout_ms=1500))
        req = wait_pending(rig)
        text = last_result(rig, 0, timeout=20)
        print("\nB4 tool result after timeout:", text[:200])
        still = pending(rig)
        print(
            "B4 pending after the tool gave up:",
            [(r["id"] == req["id"], r["action"]) for r in still],
        )
        assert [r["id"] for r in still] == [req["id"]], "the request is still pending server-side"
        reply(rig, req, "once")  # late approval
        time.sleep(1.0)
        settled = events(rig, "assert.settled")
        print(
            "B4 late 'once': settled events:",
            [(e["ok"], e["ms"]) for e in settled],
            "| tool.execute count",
            len(events(rig, "tool.execute")),
        )
        assert settled and settled[-1]["ok"] is True, "the late reply resolves the orphaned assert"
        assert not any(e["ev"] == "assert.ok" for e in log(rig)), (
            "but nothing continued after the tool had thrown"
        )
        assert pending(rig) == []

    def test_a_plugin_chosen_request_id_is_ignored_so_the_tool_must_look_it_up(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        run_prompt(rig, "dev", force(timeout_ms=1200, own_id=True, reject_on_timeout=True))
        req = wait_pending(rig)
        print("\nB4b plugin-chosen id honoured:", req["id"].startswith("per_bp"))
        last_result(rig, 0, timeout=20)
        t = events(rig, "timeout")[0]
        rj = events(rig, "timeout.reject")[0]
        print(
            "B4b reject by the chosen id:",
            rj["ok"],
            rj.get("msg"),
            "| the id the server used is in list():",
            t["pending"],
        )
        assert not req["id"].startswith("per_bp") and rj["ok"] is False
        assert [r["id"] for r in pending(rig)] == [req["id"]]
        reply(rig, req, "reject")

    def test_the_tool_can_reject_without_choosing_the_id(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        run_prompt(rig, "dev", force(timeout_ms=1200, reject_on_timeout=True))
        wait_pending(rig)
        last_result(rig, 0, timeout=20)
        rj = events(rig, "timeout.reject")[0]
        print("\nB4c reject by listed id:", rj)
        time.sleep(0.5)
        assert pending(rig) == [] and rj["ok"] is True

    def test_interrupting_the_session_while_pending(self, rig_factory: Callable[..., Rig]) -> None:
        rig = make(rig_factory)
        sid = run_prompt(rig, "dev", force())
        req = wait_pending(rig)
        out = rig.api("POST", f"/api/session/{sid}/interrupt", {})
        time.sleep(1.5)
        print(
            "\nB4d interrupt:",
            out,
            "| signal.abort events:",
            events(rig, "signal.abort"),
            "| pending:",
            [r["id"] == req["id"] for r in pending(rig)],
        )
        settled = events(rig, "assert.settled")
        print("B4d settled:", [(e["ok"], e.get("tag")) for e in settled])
        assert (
            events(rig, "signal.abort")
            and settled == []
            and [r["id"] for r in pending(rig)] == [req["id"]]
        )
        reply(rig, req, "reject")  # leave nothing behind

    def test_the_ask_content_and_a_subagent_ask(self, rig_factory: Callable[..., Rig]) -> None:
        rig = make(rig_factory)
        parent = run_prompt(rig, "build", "TASK " + force(note="from a subagent"))
        req = wait_pending(rig)
        child = req["sessionID"]
        info = rig.api("GET", f"/api/session/{child}")["data"]
        print(
            "\nB5 ask session is the child:",
            child != parent,
            "| parentID == parent:",
            info.get("parentID") == parent,
        )
        print("B5 child session keys:", sorted(info))
        print(
            "B5 ask fields:",
            sorted(req),
            "| resources:",
            req["resources"],
            "| metadata:",
            req.get("metadata"),
            "| source:",
            req.get("source"),
        )
        assert child != parent and info.get("parentID") == parent
        ev = events(rig, "tool.execute")[0]
        print("B5 caller agent in the tool:", ev["agent"])
        reply(rig, req, "reject")
        rig.wait_results(1, 20)

    def test_the_plugin_can_walk_to_the_root_session_of_a_subagent(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        parent = run_prompt(rig, "build", 'TASK FORCE bp_ctl {"op": "family"}')
        wait_for(lambda: events(rig, "ctl"))
        text = events(rig, "ctl")[0]["text"]
        print("\nB5c family walk from the child:", text)
        chain = json.loads(text)
        assert len(chain) == 2 and chain[1]["id"] == parent[:14]

    def test_a_resource_scoped_config_deny_beats_the_forcing_hook(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        agents = {
            "part": {
                "mode": "primary",
                "permissions": [
                    *ALLOW_ALL,
                    {"action": "carter_push", "resource": "o/r*", "effect": "deny"},
                ],
            }
        }
        rig = make(rig_factory, extra_config={"agents": agents})
        run_prompt(rig, "part", force())
        wait_for(lambda: events(rig, "assert.settled"))
        e = events(rig, "assert.settled")[0]
        print(
            "\nB9 resource-scoped deny: tool sees",
            e.get("tag"),
            "|",
            e.get("msg"),
            "| evaluate hook reached:",
            bool(events(rig, "evaluate")),
            "| pending:",
            pending(rig),
        )
        assert e["ok"] is False and not events(rig, "evaluate") and pending(rig) == []

    def test_pending_asks_in_two_sessions_have_separate_families(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        a = run_prompt(rig, "dev", force())
        b = run_prompt(rig, "dev", force())
        wait_for(lambda: len(pending(rig)) == 2)
        by_session = {r["sessionID"]: r for r in pending(rig)}
        assert set(by_session) == {a, b}
        reply(rig, by_session[a], "reject")
        time.sleep(0.5)
        left = pending(rig)
        print("\nB5b rejecting session A leaves B pending:", [r["sessionID"] == b for r in left])
        assert [r["sessionID"] for r in left] == [b]
        reply(rig, left[0], "reject")


# --- B: headless -----------------------------------------------------------------------------


def run_client(
    rig: Rig, *args: str, env: dict[str, str] | None = None, timeout: float = 90.0
) -> tuple[int, str]:
    """``opencode run --server <rig>`` in the rig environment (netns included)."""
    done = rig.run(
        [
            "env",
            *(f"{k}={v}" for k, v in (env or {}).items()),
            rig.opencode,
            "run",
            "--server",
            f"http://127.0.0.1:{rig.port}",
            *args,
        ],
        timeout=timeout,
    )
    return done.returncode, (done.stdout + done.stderr)


class TestSpikeBHeadless:
    def test_run_without_auto_rejects_in_milliseconds(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        t0 = time.time()
        rc, out = run_client(rig, "--agent", "dev", force())
        print(
            f"\nB6 run (no --auto): rc={rc} in {time.time() - t0:.1f}s; settled={[(e['ok'], e.get('tag'), e['ms']) for e in events(rig, 'assert.settled')]}"
        )
        print("B6 output tail:", out.strip().splitlines()[-3:])
        assert events(rig, "assert.settled") and events(rig, "assert.settled")[0]["ok"] is False
        assert pending(rig) == []

    def test_run_with_auto_approves_in_milliseconds_and_the_dwell_floor_catches_it(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = make(rig_factory)
        rows = []
        for _ in range(5):
            before = len(events(rig, "assert.ok"))
            run_client(rig, "--agent", "dev", "--auto", force())
            ok = events(rig, "assert.ok")
            rows.append(ok[-1]["dwell_ms"] if len(ok) > before else None)
        print("\nB7 --auto dwell ms:", rows)
        assert all(r is not None and r < 150 for r in rows)
        _, out = run_client(rig, "--agent", "dev", "--auto", force(min_dwell_ms=150))
        assert "refused" in out, out[-300:]

    def test_headless_profile_via_standalone_denies_and_via_server_does_not(
        self, rig_factory: Callable[..., Rig], tmp_path: Path
    ) -> None:
        rig = make(rig_factory)
        profile = rig.home / "headless.json"
        profile.write_text(
            json.dumps(
                {"agents": {"dev": {"mode": "primary", "permissions": [*ALLOW_ALL, *DENY_B]}}}
            )
        )
        # (a) client against the already running server: OPENCODE_CONFIG belongs to the client process only
        rc, out = run_client(
            rig, "--agent", "dev", "--auto", force(), env={"OPENCODE_CONFIG": str(profile)}
        )
        reached_a = len(events(rig, "tool.execute"))
        print(f"\nB8a --server + OPENCODE_CONFIG: tool reached={reached_a}")
        # (b) standalone: a private server reads the profile
        before = len(log(rig))
        done = rig.run(
            [
                "env",
                f"OPENCODE_CONFIG={profile}",
                rig.opencode,
                "run",
                "--standalone",
                "--agent",
                "dev",
                "--auto",
                force(),
            ],
            timeout=120,
        )
        tail = (done.stdout + done.stderr).strip().splitlines()[-4:]
        reached_b = [
            e["ev"] for e in log(rig)[before:] if e["ev"] in ("tool.execute", "execute.before")
        ]
        print(
            f"B8b --standalone + OPENCODE_CONFIG: rc={done.returncode} events={reached_b} tail={tail}"
        )
        print(
            f"B8 note: standalone also loads the plugin from the isolated HOME: {bool(reached_b)}"
        )
        assert reached_b == ["execute.before"], "denied before the tool or the permission hook ran"
        assert "No tool named" in "".join(tail)

    def test_headless_profile_in_the_default_service_mode(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        """`opencode run` without --server/--standalone talks to the background service (here: the
        rig's isolated one, on its own port). A profile in OPENCODE_CONFIG is read by whichever
        process starts the service."""
        rig = make(rig_factory)
        profile = rig.home / "headless.json"
        profile.write_text(
            json.dumps(
                {"agents": {"dev": {"mode": "primary", "permissions": [*ALLOW_ALL, *DENY_B]}}}
            )
        )
        env = ["env", f"OPENCODE_CONFIG={profile}"]
        before = len(log(rig))
        first = rig.run(
            [*env, rig.opencode, "run", "--agent", "dev", "--auto", force(mode="noassert")],
            timeout=120,
        )
        print(
            f"\nB8c service started BY the profiled run: rc={first.returncode} tail={(first.stdout + first.stderr).strip().splitlines()[-2:]}"
        )
        print(
            "B8c   plugin events (this is the service's own plugin load, if any):",
            [e["ev"] for e in log(rig)[before:]][:6],
        )
        second = rig.run(
            [rig.opencode, "run", "--agent", "dev", "--auto", force(mode="noassert")], timeout=120
        )
        print(
            f"B8c second run without the profile, same service: rc={second.returncode} tail={(second.stdout + second.stderr).strip().splitlines()[-2:]}"
        )
        assert "No tool named" in first.stdout + first.stderr
        assert "No tool named" in second.stdout + second.stderr, (
            "the profile sticks to the service its run started"
        )
        rig.stop_service()


class TestSpikeAInstalled:
    """Carter's own installer writes the denies; devops is exempt (spike D, re-checked for the new tools)."""

    def test_devops_asks_and_others_are_denied_with_the_real_install(
        self, rig_factory: Callable[..., Rig]
    ) -> None:
        rig = rig_factory(opencode=_BINARY[0], plugins={"bp": PROBE})
        done = rig.run([*CARTER, "install", "--yes"])
        assert done.returncode == 0, done.stdout[-600:] + done.stderr[-600:]
        # slice B shipped the real tools: this spike's stand-ins own the names, so B goes off
        off = rig.run([*CARTER, "guard", "remove", "--yes", "--only", "broker"])
        assert off.returncode == 0, off.stdout[-600:] + off.stderr[-600:]
        rig.restart()
        run_prompt(rig, "build", FORCE)
        assert "No tool named" in last_result(rig, 0)
        run_prompt(rig, "carter-devops", FORCE)
        req = wait_pending(rig)
        print("\nA7 devops ask (real install):", req["action"], req["resources"])
        agents = [e["agent"] for e in events(rig, "tool.execute")]
        print("A7 agent id seen by the tool for devops:", agents)
        assert agents == ["carter-devops"]
        reply(rig, req, "reject")
        # a Carter agent other than devops and a subagent are denied
        n = len(rig.results())
        run_prompt(rig, "carter-engineer", FORCE)
        assert "No tool named" in last_result(rig, n)
        n = len(rig.results())
        run_prompt(rig, "carter-devops", "TASK " + FORCE)
        time.sleep(4)
        print(
            "A7 devops -> subagent(general): results",
            [r["result"][:90] for r in rig.results()[n:]],
            "| pending asks:",
            len(pending(rig)),
            "| tool.execute agents:",
            [e["agent"] for e in events(rig, "tool.execute")],
        )
        rig.stop_service()
