"""Spike C (plan 004, step 4): the self-test round trip (RFC-0007 App C.2, D56) on two versions.

Opt-in (``CARTER_E2E=1``). Run on the second version with ``CARTER_E2E_OPENCODE_ALT=<path>``.
The probe is ``probes/selftest.ts``; step 13 turns its state machine into the plugin core and
step 32 into the contract suite. When ``CARTER_E2E_RECORD=<file>`` is set every scenario appends
a JSON line (version, scenario, result, ms) for ``notes.md``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from e2e.harness import Rig

pytestmark = pytest.mark.e2e

PROBE = (Path(__file__).parent / "probes" / "selftest.ts").read_text()
NAMES = (
    "env | cut -d= -f1 | grep -E '^(AGENT|OPENCODE_SESSION_ID|CARTER_.*)$' | sort | tr '\\n' ' '"
)
N_MS = 500  # injected so the failure paths are quick; one test below uses the default 2000


def record(version: str, scenario: str, result: str, ms: float | None = None) -> None:
    target = os.environ.get("CARTER_E2E_RECORD")
    if target:
        with open(target, "a") as f:
            f.write(
                json.dumps({"version": version, "scenario": scenario, "result": result, "ms": ms})
                + "\n"
            )


def log(rig: Rig) -> list[dict[str, Any]]:
    path = rig.logs / "selftest.log"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def state_events(rig: Rig) -> list[dict[str, Any]]:
    return [e for e in log(rig) if e["ev"] == "state"]


def last_tag(rig: Rig) -> str:
    return [e for e in log(rig) if e["ev"] == "create"][-1]["tag"]


def agent_shell(rig: Rig, command: str = NAMES) -> set[str]:
    sid = rig.new_session()
    seen = len(rig.results())
    rig.prompt(sid, f"RUN {command}")
    return set(str(rig.wait_results(seen + 1)[-1]["result"]).split())


def bang(rig: Rig, command: str = NAMES) -> set[str]:
    sid = rig.new_session()
    rig.bang(sid, command)
    deadline = time.time() + 10
    while time.time() < deadline:
        shells = [
            m for m in rig.api("GET", f"/api/session/{sid}/context")["data"] if m["type"] == "shell"
        ]
        if shells and shells[0].get("status") == "exited":
            return set(shells[0]["output"]["output"].split())
        time.sleep(0.2)
    raise AssertionError("the ! shell did not finish")


def make(rig_factory, opencode_bin, variant: str = "ok", n_ms: int = N_MS, **kw: Any) -> Rig:
    env = {"PROBE_VARIANT": variant, "PROBE_N_MS": str(n_ms), **kw.pop("server_env_extra", {})}
    return rig_factory(
        opencode=opencode_bin, plugins={"selftest": PROBE}, server_env_extra=env, **kw
    )


def wait_for(rig: Rig, to: str, timeout: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        hit = [e for e in state_events(rig) if e["to"] == to]
        if hit:
            return hit[0]
        time.sleep(0.05)
    raise AssertionError(f"state never became {to}: {log(rig)}")


# (a) --------------------------------------------------------------------------------------


def test_agent_shell_round_trip_passes(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin)
    assert state_events(rig) == []  # starts unproven
    names = agent_shell(rig)
    passed = wait_for(rig, "passed")
    assert passed["round_trip_ms"] < 100
    assert "CARTER_AGENT_SHELL" in names and "CARTER_HUMAN_SHELL" not in names
    assert "AGENT" in names and "OPENCODE_SESSION_ID" in names  # AD1 inputs are there too
    record(opencode_bin.version, "a agent shell round trip", "passed", passed["round_trip_ms"])


# (b) --------------------------------------------------------------------------------------


def test_subagent_shell_is_a_round_trip_and_gets_the_agent_tag(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin)
    sid = rig.new_session()
    rig.prompt(sid, f"TASK RUN {NAMES}")
    rig.wait_results(2)
    passed = wait_for(rig, "passed")
    assert last_tag(rig) == "agent"
    record(opencode_bin.version, "b subagent shell", "passed", passed["round_trip_ms"])


# (c) --------------------------------------------------------------------------------------


def test_bang_is_untagged_while_unproven_and_human_only_after_a_pass(
    rig_factory, opencode_bin
) -> None:
    rig = make(rig_factory, opencode_bin)
    early = bang(rig)
    assert last_tag(rig) == "none"
    assert state_events(rig) == []  # a ! shell proves nothing
    assert not {"CARTER_HUMAN_SHELL", "CARTER_AGENT_SHELL", "AGENT"} & early
    agent_shell(rig)
    wait_for(rig, "passed")
    late = bang(rig)
    assert last_tag(rig) == "human"
    assert (
        "CARTER_HUMAN_SHELL" in late and "AGENT" not in late and "OPENCODE_SESSION_ID" not in late
    )
    record(opencode_bin.version, "c ! unproven then passed", "no tag, then human tag")


# (d) broken orders ------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["strip_in_exec", "skip_create"])
def test_a_broken_hook_order_ends_in_failed_and_every_shell_is_an_agent_shell(
    rig_factory, opencode_bin, variant: str
) -> None:
    rig = make(rig_factory, opencode_bin, variant=variant)
    agent_shell(rig)
    failed = wait_for(rig, "failed")
    assert N_MS <= failed["after_ms"] < N_MS + 300
    assert not [e for e in state_events(rig) if e["to"] == "passed"]
    after_agent = agent_shell(rig)
    after_bang = bang(rig)  # the human's shell is now treated like an agent shell
    assert last_tag(rig) == "agent"
    assert "CARTER_AGENT_SHELL" in after_agent and "CARTER_AGENT_SHELL" in after_bang
    assert not any("CARTER_HUMAN_SHELL" in n for n in (after_agent, after_bang))
    assert "AGENT" in after_agent  # AD1's native signal is still there for the guard
    record(opencode_bin.version, f"d broken order ({variant})", "failed", failed["after_ms"])


def test_default_timeout_is_two_seconds(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin, variant="skip_create", n_ms=2000)
    agent_shell(rig)
    failed = wait_for(rig, "failed", timeout=6)
    assert 2000 <= failed["after_ms"] < 2300
    record(opencode_bin.version, "d default N=2000", "failed", failed["after_ms"])


# (e) polluted server env ------------------------------------------------------------------


def test_polluted_server_env_gets_no_human_tag_and_one_warning(rig_factory, opencode_bin) -> None:
    polluted = {"AGENT": "1", "OPENCODE_SESSION_ID": "ses_polluted", "CARTER_AGENT_SHELL": "1"}
    rig = make(rig_factory, opencode_bin, server_env_extra=polluted)
    agent_shell(rig)
    wait_for(rig, "passed")
    first, second = bang(rig), bang(rig)
    assert last_tag(rig) == "none"
    assert "CARTER_HUMAN_SHELL" not in first | second
    warns = [e for e in log(rig) if e["ev"] == "warn"]
    assert len(warns) == 1 and set(warns[0]["names"]) == {
        "AGENT",
        "OPENCODE_SESSION_ID",
        "CARTER_AGENT_SHELL",
    }
    record(opencode_bin.version, "e polluted env in passed", "no human tag, 1 warning")


# (f) concurrency --------------------------------------------------------------------------


def test_two_concurrent_shell_calls_have_no_race(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin)
    sid = rig.new_session()
    rig.prompt(sid, "RUNPAR echo A ::: echo B")
    assert sorted(r["result"] for r in rig.wait_results(2)) == ["A\n", "B\n"]
    wait_for(rig, "passed")
    time.sleep(N_MS / 1000 + 0.4)  # past the timeout: no stray timer may fail the state
    assert [e["to"] for e in state_events(rig)] == ["passed"]
    assert [e["tag"] for e in log(rig) if e["ev"] == "create"] == ["agent", "agent"]
    assert log(rig)[-1]["pending"] == 0
    record(opencode_bin.version, "f two concurrent calls", "passed, no race")


# (g) exceptions ---------------------------------------------------------------------------

REJECTOR = """import { Plugin } from "@opencode/plugin"
export default Plugin.define({
  id: "zz-reject",
  setup(ctx: any) {
    ctx.tool.hook("execute.before", (e: any) => {
      if (e.tool === "shell" && String(e.input?.command).includes("PROBE_LATE")) {
        throw new Error("probe: rejected by a later plugin")
      }
    })
  },
})
"""


def test_a_rejection_before_arming_does_not_fail_the_self_test(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin)
    assert "error" in agent_shell_text(rig, "echo PROBE_REJECT")
    time.sleep(N_MS / 1000 + 0.4)
    assert state_events(rig) == []  # still unproven, not failed
    record(opencode_bin.version, "g reject before arming", "stays unproven")


def test_arming_before_a_rejection_would_fail_the_self_test_falsely(
    rig_factory, opencode_bin
) -> None:
    """The hazard: arm the timer FIRST and the first gate rejection ends in ``failed``."""
    rig = make(rig_factory, opencode_bin, variant="arm_first")
    assert "error" in agent_shell_text(rig, "echo PROBE_REJECT")
    failed = wait_for(rig, "failed")
    record(opencode_bin.version, "g arm first then reject", "false failed", failed["after_ms"])


def test_a_later_plugins_rejection_after_our_marker_fails_the_self_test(
    rig_factory, opencode_bin
) -> None:
    """Hook order across plugins: if ours runs first and another plugin rejects, no create.before
    follows and the state becomes ``failed``. Observed here; the design must absorb it (step 8)."""
    rig = make(
        rig_factory,
        opencode_bin,
        extra_files={".config/opencode/plugins/zz-reject/index.ts": REJECTOR},
    )
    out = agent_shell_text(rig, "echo PROBE_LATE")
    assert "rejected by a later plugin" in out
    order = [e for e in log(rig) if e["ev"] == "setup"]
    assert len(order) == 1
    failed = wait_for(rig, "failed")
    record(opencode_bin.version, "g later plugin rejects", "false failed", failed["after_ms"])


def agent_shell_text(rig: Rig, command: str) -> str:
    sid = rig.new_session()
    seen = len(rig.results())
    rig.prompt(sid, f"RUN {command}")
    return str(rig.wait_results(seen + 1)[-1]["result"])
