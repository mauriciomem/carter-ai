"""Spike D (plan 004, step 5): per-agent denies in ``opencode debug agents`` and deny-before-hook.

Opt-in (``CARTER_E2E=1``). Carter's real 1G installer runs inside the isolated HOME of the rig
(``carter install --yes``); nothing touches the developer's config. Probe: ``probes/deny_probe.ts``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from e2e.g2 import CARTER
from e2e.harness import Rig

pytestmark = pytest.mark.e2e

PROBE = (Path(__file__).parent / "probes" / "deny_probe.ts").read_text()
ACTIONS = ("carter_push",)
FORCE = 'FORCE carter_push {"ref": "x"}'
DENY = {"carter_push": {"action": "carter_push", "resource": "*", "effect": "deny"}}


def installed_rig(rig_factory, **kw: Any) -> Rig:
    """A rig with the 1G guards installed by Carter's own installer, then restarted."""
    rig = rig_factory(plugins={"dp": PROBE}, **kw)
    done = rig.run([*CARTER, "install", "--yes"])
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
    # Slice B: the real carter_push now exists; this spike is about the stand-in probe tools, so
    # B goes off (g2 back to revision 2) and the probe owns the names. The real ones are
    # tested in test_b_contract.py.
    off = rig.run([*CARTER, "guard", "remove", "--yes", "--only", "broker"])
    assert off.returncode == 0, off.stdout[-800:] + off.stderr[-800:]
    rig.restart()
    return rig


def agents_by_id(rig: Rig) -> dict[str, dict[str, Any]]:
    return {a["id"]: a for a in json.loads(rig.debug("agents"))}


def probe_log(rig: Rig) -> list[dict[str, Any]]:
    path = rig.logs / "deny-probe.log"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def ask(
    rig: Rig, agent: str, prompt: str, wait: float = 2.5
) -> tuple[list[str], list[dict[str, Any]]]:
    """One prompt in a session of ``agent``; returns (new tool results, new probe events)."""
    sid = rig.api("POST", "/api/session", {"agent": agent})["data"]["id"]
    seen_results, seen_events = len(rig.results()), len(probe_log(rig))
    rig.prompt(sid, prompt)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(0.2)
    return [r["result"] for r in rig.results()[seen_results:]], probe_log(rig)[seen_events:]


def test_debug_agents_carries_the_denies_in_14_of_15_agents(rig_factory) -> None:
    rig = installed_rig(rig_factory)
    agents = agents_by_id(rig)
    assert len(agents) == 15
    for agent in agents.values():
        assert {"id", "name", "request", "mode", "hidden", "permissions"} <= set(agent)
    exempt = {"carter-devops"}
    for agent_id, agent in agents.items():
        rules = agent["permissions"]
        for action in ACTIONS:
            has = {"action": action, "resource": "*", "effect": "deny"} in rules
            assert has is (agent_id not in exempt), f"{agent_id} {action}"
        assert rules[-1] == {"action": "browser", "resource": "*", "effect": "deny"}
    # the rule is just before OpenCode's last rule, so it is the last one matching `carter_push`
    build = agents["build"]["permissions"]
    assert build[-2:-1] == [
        {"action": "carter_push", "resource": "*", "effect": "deny"},
    ]
    # built-ins and Carter agents alike
    assert {"build", "plan", "general", "explore", "carter-engineer", "carter-maestro"} <= set(
        agents
    )
    # the providers survived the install (the guard that matters most)
    assert rig.provider_ids == ["mock"]


@pytest.mark.parametrize(
    "bad",
    [
        [{"action": "carter_push", "resource": "*", "effect": "nope"}],  # invalid effect
        [{"action": "carter_push", "effect": "deny"}],  # missing resource
    ],
    ids=["bad-effect", "missing-resource"],
)
def test_one_invalid_rule_drops_the_agents_whole_entry(
    rig_factory, bad: list[dict[str, str]]
) -> None:
    config = {
        "agents": {
            "build": {"permissions": [DENY["carter_push"], *bad]},
            "plan": {"permissions": [DENY["carter_push"]]},
        }
    }
    rig = rig_factory(extra_config=config)
    agents = agents_by_id(rig)
    assert DENY["carter_push"] not in agents["build"]["permissions"]  # the valid rule went with it
    assert DENY["carter_push"] in agents["plan"]["permissions"]  # a sibling entry is unaffected
    info = [d["info"] for d in json.loads(rig.debug("config")) if "info" in d][0]
    assert set(info["agents"]) == {"plan"}  # `debug config` shows the entry is gone
    diagnostics = [
        x
        for x in (rig.logs / "server.log").read_text().splitlines()
        if "normalization diagnostic" in x
    ]
    assert diagnostics
    assert all(
        "path=$.agents.build" in x and "skipped malformed recognized value" in x
        for x in diagnostics
    )


def test_a_denied_agent_is_never_offered_the_tool_and_a_forced_call_reaches_nothing(
    rig_factory,
) -> None:
    rig = installed_rig(rig_factory)
    cfg = json.loads(rig.config_file.read_text())
    cfg["agents"]["ctl"] = {
        "mode": "primary",
        "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
    }
    rig.config_file.write_text(json.dumps(cfg, indent=2))
    rig.restart()

    results, events = ask(rig, "build", FORCE)
    request_tools = [
        json.loads(x)["tools"] for x in (rig.logs / "requests.jsonl").read_text().splitlines()
    ]
    assert not any("carter_push" in tools for tools in request_tools if tools)  # not even offered
    (text,) = results
    assert json.loads(text) == {
        "error": {
            "type": "tool.execution",
            "message": (
                'No tool named "carter_push" is currently available. '
                "Please use a tool from the available tool list."
            ),
        },
        "content": [],
    }
    # the hook sees the attempt (execute.before) but neither the tool nor `evaluate` is reached
    assert [(e["ev"], e.get("tool")) for e in events] == [("execute.before", "carter_push")]

    # control 1: an agent without the rule reaches the tool and `evaluate` (effect in: allow)
    results, events = ask(rig, "ctl", FORCE)
    assert results == ["carter_push ran"]
    assert [e["ev"] for e in events] == ["execute.before", "tool.execute", "evaluate", "assert.ok"]
    evaluate = next(e for e in events if e["ev"] == "evaluate")
    assert (evaluate["action"], evaluate["effect_in"]) == ("carter_push", "allow")
    assert evaluate["keys"] == [
        "action",
        "agent",
        "effect",
        "metadata",
        "resources",
        "sessionID",
        "source",
    ]

    # control 2: devops (exempt) reaches `evaluate` with `ask` and waits for a human
    results, events = ask(rig, "carter-devops", FORCE)
    assert results == []  # pending permission request, no answer
    evaluate = next(e for e in events if e["ev"] == "evaluate")
    assert evaluate["effect_in"] == "ask"
    assert not [e for e in events if e["ev"] == "assert.ok"]
