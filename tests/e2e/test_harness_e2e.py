"""The harness proves itself against a real OpenCode (opt-in: ``CARTER_E2E=1``).

A no-op plugin is loaded, the mock model is scripted to run ``echo ok`` through the agent shell
tool, and the result is read back through the HTTP API (not from the mock's log).
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.e2e

NOOP_PLUGIN = """import { Plugin } from "@opencode/plugin"
import { appendFileSync } from "node:fs"

export default Plugin.define({
  id: "noop",
  setup(ctx: any) {
    appendFileSync("__LOGS__/plugin.log", JSON.stringify({ ev: "setup" }) + "\\n")
  },
})
"""


def test_one_mock_driven_shell_call_round_trips(rig_factory) -> None:
    rig = rig_factory(plugins={"noop": NOOP_PLUGIN})

    assert rig.provider_ids == ["mock"]
    sid = rig.new_session()
    rig.prompt(sid, "RUN echo ok")
    rig.wait_results(1)

    messages = rig.api("GET", f"/api/session/{sid}/context")["data"]
    tools = [
        p
        for m in messages
        for p in m.get("content", [])
        if isinstance(p, dict) and p.get("type") == "tool"
    ]
    assert [t["name"] for t in tools] == ["shell"]
    assert tools[0]["state"]["status"] == "completed"
    assert tools[0]["state"]["content"] == [{"type": "text", "text": "ok\n"}]

    log = (rig.logs / "plugin.log").read_text()
    assert '"ev":"setup"' in log.replace(" ", "")
    requests = [json.loads(line) for line in (rig.logs / "requests.jsonl").read_text().splitlines()]
    assert {r["model"] for r in requests} == {"mock-1"}  # only the mock served the model


def test_rig_runs_in_its_own_home_and_leaves_the_real_one_alone(rig_factory, real_home) -> None:
    rig = rig_factory()
    assert rig.home != real_home
    assert real_home not in rig.home.parents
    env_names = json.loads((rig.logs / "rig.json").read_text())["env_names"]
    assert "SSH_AUTH_SOCK" not in env_names
    assert "OPENCODE_SESSION_ID" not in env_names
    assert "HOME" in env_names
