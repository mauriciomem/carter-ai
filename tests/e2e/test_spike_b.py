"""Spike B (plan 004, step 3): what OpenCode's plugin API really does, pinned as e2e tests.

Opt-in (``CARTER_E2E=1``). Observed on OpenCode 2.1.4 (source cross-checked in the v2.1.4 tree).
Step 32 extends these into the compatibility contract (RFC-0007 App C.8). The probe plugin is
``probes/ground_truth.ts``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from e2e.harness import Rig

pytestmark = pytest.mark.e2e

PROBE = (Path(__file__).parent / "probes" / "ground_truth.ts").read_text()
# Variable names only (never values) that an agent or user shell carries.
ENV_NAMES = (
    "env | cut -d= -f1 | grep -E '^(AGENT|AI_AGENT|OPENCODE.*|SSH_AUTH_SOCK|GITHUB_TOKEN|GH_TOKEN"
    "|PROBE_.*|CARTER.*)$' | sort | tr '\\n' ' '"
)
SERVER_ENV = {"SSH_AUTH_SOCK": "/tmp/fake-agent.sock", "GITHUB_TOKEN": "not-a-token"}

HOOKY = """import { Plugin } from "@opencode/plugin"
import { appendFileSync } from "node:fs"
const w = (o: any) => appendFileSync("__LOGS__/plugin.log", JSON.stringify(o) + "\\n")
const NONCE = Math.random().toString(36).slice(2, 8)
export default Plugin.define({
  id: "NAME",
  setup(ctx: any) {
    w({ ev: "setup", name: "NAME", nonce: NONCE, options: ctx.options ?? null })
    ctx.tool.hook("execute.before", () => w({ ev: "execute.before", name: "NAME", nonce: NONCE }))
    ctx.shell.hook("create.before", () => w({ ev: "create.before", name: "NAME", nonce: NONCE }))
    THROW
    return () => w({ ev: "cleanup", name: "NAME", nonce: NONCE })
  },
})
"""


def hooky(name: str, throw: str = "") -> str:
    return HOOKY.replace("NAME", name).replace("THROW", throw)


def events(rig: Rig) -> list[dict[str, Any]]:
    path = rig.logs / "plugin.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def names_of(rig: Rig, *, ev: str) -> list[dict[str, Any]]:
    return [e for e in events(rig) if e["ev"] == ev]


def run_shell(rig: Rig, command: str, *, timeout: float = 15.0) -> str:
    """One agent shell call through the mock model; returns the tool result text."""
    sid = rig.new_session()
    seen = len(rig.results())
    rig.prompt(sid, f"RUN {command}")
    return str(rig.wait_results(seen + 1, timeout)[-1]["result"])


def server_log_plugin_lines(rig: Rig) -> list[str]:
    lines = (rig.logs / "server.log").read_text().splitlines()
    return [x for x in lines if "plugin" in x.lower() and "watcher" not in x]


# --- Q1/Q2: registration ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "files",
    [
        {".config/opencode/plugins/gt/index.ts": PROBE},  # directory with index.ts
        {".config/opencode/plugins/gt.ts": PROBE},  # single file
        {".config/opencode/plugin/gt.ts": PROBE},  # singular directory name
    ],
    ids=["plugins-dir-index", "plugins-file", "plugin-singular-dir"],
)
def test_global_config_dir_forms_load_a_ts_plugin_directly(
    rig_factory, files: dict[str, str]
) -> None:
    rig = rig_factory(extra_files=files)
    assert [e["app"]["version"] for e in names_of(rig, ev="setup")] != []
    assert any('msg="loading plugin"' in x for x in server_log_plugin_lines(rig))


def test_project_opencode_plugins_dir_also_loads(rig_factory) -> None:
    """A repo can ship a plugin: why the 1G deny on ``.opencode/**`` matters (RFC D48)."""
    rig = rig_factory(ws_files={".opencode/plugins/proj.ts": hooky("proj")})
    assert [e["name"] for e in names_of(rig, ev="setup")] == ["proj"]


def _config_rig(rig_factory, entry_for: str, files: dict[str, str]) -> Rig:
    """Rigs need their base dir before the config can name an absolute path; use a relative one."""
    return rig_factory(extra_files=files, extra_config={"plugins": [entry_for]})


def test_config_plugins_relative_entries_are_resolved_against_the_config_dir(rig_factory) -> None:
    rig = _config_rig(rig_factory, "./ext/n", {".config/opencode/ext/n/index.ts": hooky("n")})
    assert [e["name"] for e in names_of(rig, ev="setup")] == ["n"]


def test_config_plugins_ts_file_entry_is_dropped_with_a_warning_only(rig_factory) -> None:
    rig = _config_rig(rig_factory, "./ext/f.ts", {".config/opencode/ext/f.ts": hooky("f")})
    assert names_of(rig, ev="setup") == []
    assert any(
        "must be a directory" in x for x in (rig.logs / "server.log").read_text().splitlines()
    )
    assert run_shell(rig, "echo still-works").strip() == "still-works"  # the server is fine


def test_config_plugins_object_form_passes_options(rig_factory) -> None:
    rig = rig_factory(
        extra_files={".config/opencode/ext/o/index.ts": hooky("o")},
        extra_config={"plugins": [{"package": "./ext/o", "options": {"k": "v"}}]},
    )
    assert names_of(rig, ev="setup")[0]["options"] == {"k": "v"}


def test_missing_configured_plugin_is_logged_and_does_not_stop_the_others(rig_factory) -> None:
    rig = rig_factory(
        plugins={"good": hooky("good")},
        extra_config={"plugins": ["./does/not/exist"]},
    )
    assert [e["name"] for e in names_of(rig, ev="setup")] == ["good"]
    assert any("failed to load plugin" in x for x in server_log_plugin_lines(rig))
    docs = json.loads(rig.debug("config"))
    # the dropped entry is STILL listed by `debug config`: it proves registration, never loading
    assert any("plugins" in d.get("info", {}) for d in docs)


def test_dir_discovered_plugin_is_invisible_to_debug_config_and_plugin_list(rig_factory) -> None:
    rig = rig_factory(plugins={"good": hooky("good")})
    docs = json.loads(rig.debug("config"))
    assert all("plugins" not in d.get("info", {}) for d in docs)
    assert [d["type"] for d in docs] == ["document", "directory"]


@pytest.mark.parametrize(
    ("name", "source", "fragment"),
    [
        ("syntax", "export default Plugin.define({ id: 'x', setup( {{{\n", "failed to load plugin"),
        ("nodefault", "export const x = 1\n", "must export a default definition"),
    ],
)
def test_a_broken_plugin_file_is_skipped_with_a_warning(
    rig_factory, name: str, source: str, fragment: str
) -> None:
    rig = rig_factory(
        plugins={"good": hooky("good")}, extra_files={f".config/opencode/plugins/{name}.ts": source}
    )
    assert [e["name"] for e in names_of(rig, ev="setup")] == ["good"]
    assert any(fragment in x for x in server_log_plugin_lines(rig))
    assert run_shell(rig, "echo ok").strip() == "ok"


def test_sibling_helper_files_work_in_directory_form_only(rig_factory) -> None:
    index = (
        hooky("dirform")
        .replace(
            'import { appendFileSync } from "node:fs"',
            'import { appendFileSync } from "node:fs"\nimport { answer } from "./core.ts"',
        )
        .replace("nonce: NONCE,", "nonce: NONCE, answer,")
    )
    rig = rig_factory(
        plugins={"dirform": index},
        extra_files={
            ".config/opencode/plugins/dirform/core.ts": "export const answer = 42\n",
            ".config/opencode/plugins/loose.ts": "export const x = 1\n",
        },
    )
    assert names_of(rig, ev="setup")[0]["answer"] == 42
    # a loose helper next to plugin files is itself treated as a plugin and rejected
    assert any(
        "loose.ts" in x and "failed to load plugin" in x for x in server_log_plugin_lines(rig)
    )


# --- Q3: hook shapes and env mutation --------------------------------------------------------


def test_hook_event_shapes_and_the_marker_round_trip(rig_factory) -> None:
    rig = rig_factory(plugins={"gt": PROBE}, server_env_extra=SERVER_ENV)
    result = run_shell(rig, ENV_NAMES)
    before = names_of(rig, ev="execute.before")[0]
    create = names_of(rig, ev="create.before")[0]
    assert before["keys"] == ["agent", "id", "input", "messageID", "sessionID", "tool"]
    assert before["tool"] == "shell"
    assert before["agent"] == "build"
    assert before["input_keys"] == ["command"]
    assert create["keys"] == ["command", "cwd", "env", "shell", "timeout"]
    assert create["marker"] is True  # the marker added in execute.before arrived in create.before
    assert create["timeout"] == 120000
    # create.before sees the server env (+ TERM, OPENCODE_TERMINAL) but NOT the agent identity:
    assert "AGENT" not in create["env_names_before"]
    assert "OPENCODE_SESSION_ID" not in create["env_names_before"]
    assert "SSH_AUTH_SOCK" in create["env_names_before"]
    # ... which OpenCode adds only after the hook ran (so a plugin cannot delete them):
    names = result.split()
    assert {"AGENT", "AI_AGENT", "OPENCODE", "OPENCODE_SESSION_ID", "OPENCODE_TERMINAL"} <= set(
        names
    )


def test_create_before_can_set_delete_and_undefined_means_delete(rig_factory) -> None:
    rig = rig_factory(plugins={"gt": PROBE}, server_env_extra=SERVER_ENV)
    names = set(run_shell(rig, ENV_NAMES).split())
    assert "SSH_AUTH_SOCK" not in names  # delete env.X
    assert "GITHUB_TOKEN" not in names  # env.X = undefined behaves like delete
    assert "PROBE_UNDEF" not in names  # ... also for a key that did not exist
    assert {"PROBE_SET", "GH_TOKEN", "PROBE_AGENT_TAG"} <= names
    kinds = names_of(rig, ev="create.before")[0]["env_kinds_before"]
    assert kinds["SSH_AUTH_SOCK"] == "string"


def test_the_marker_never_reaches_the_command_or_the_stored_tool_input(rig_factory) -> None:
    rig = rig_factory(plugins={"gt": PROBE})
    sid = rig.new_session()
    rig.prompt(sid, "RUN echo plain")
    rig.wait_results(1)
    messages = rig.api("GET", f"/api/session/{sid}/context")["data"]
    tools = [
        p
        for m in messages
        for p in m.get("content", [])
        if isinstance(p, dict) and p.get("type") == "tool"
    ]
    assert tools[0]["state"]["input"]["command"] == "echo plain"  # the model/UI see no marker
    assert tools[0]["state"]["content"][0]["text"] == "plain\n"


def test_shell_tool_input_carries_workdir_and_the_default_cwd_only_appears_in_create_before(
    rig_factory,
) -> None:
    """The gate needs the effective directory: ``input.workdir`` if given, else the session's."""
    rig = rig_factory(plugins={"gt": PROBE})
    sid = rig.new_session()
    rig.prompt(
        sid, "CALL shell " + json.dumps({"command": "pwd", "workdir": "/tmp", "timeout": 5000})
    )
    assert rig.wait_results(1)[-1]["result"].strip() == "/tmp"
    rig.prompt(sid, "RUN pwd")
    assert rig.wait_results(2)[-1]["result"].strip() == str(rig.ws)
    first, second = names_of(rig, ev="execute.before")
    assert first["workdir"] == "/tmp" and first["input_keys"] == ["command", "timeout", "workdir"]
    assert second["workdir"] is None  # absent: the plugin must fall back to the session directory
    assert [e["cwd"] for e in names_of(rig, ev="create.before")] == ["/tmp", str(rig.ws)]
    assert names_of(rig, ev="create.before")[0]["timeout"] == 5000


# --- Q4: throws ------------------------------------------------------------------------------


def test_throw_in_execute_before_blocks_the_call_and_the_model_sees_the_message(
    rig_factory, tmp_path: Path
) -> None:
    rig = rig_factory(plugins={"gt": PROBE})
    witness = rig.ws / "execute-ran"
    result = json.loads(run_shell(rig, f"touch {witness}; echo PROBE_THROW_EXEC"))
    assert result["error"]["message"] == "probe: execute.before refused this command (rule R-PROBE)"
    assert not witness.exists()
    assert names_of(rig, ev="create.before") == []  # create.before never ran
    assert run_shell(rig, "echo next").strip() == "next"  # one call fails, the session goes on


def test_throw_in_create_before_stops_the_command_and_is_also_model_visible(rig_factory) -> None:
    rig = rig_factory(plugins={"gt": PROBE})
    witness = rig.ws / "create-ran"
    result = json.loads(run_shell(rig, f"touch {witness}; echo PROBE_THROW_CREATE"))
    assert result["error"]["message"] == "probe: create.before refused this shell"
    assert not witness.exists()
    assert run_shell(rig, "echo next").strip() == "next"


def test_throw_in_setup_skips_the_plugin_and_disposes_its_hooks(rig_factory) -> None:
    rig = rig_factory(
        plugins={
            "bad": hooky("bad", 'throw new Error("probe: late setup failure")'),
            "good": hooky("good"),
        }
    )
    run_shell(rig, "echo hi")
    assert {e["name"] for e in names_of(rig, ev="setup")} == {"bad", "good"}
    hooked = {e["name"] for e in events(rig) if e["ev"] in ("execute.before", "create.before")}
    assert hooked == {"good"}  # the failed plugin's hooks were registered, then removed
    assert any(
        "failed to load plugin" in x and "late setup failure" in x
        for x in server_log_plugin_lines(rig)
    )


# --- Q5: which shells fire create.before -----------------------------------------------------


def test_agent_subagent_bang_and_pty_shells(rig_factory) -> None:
    rig = rig_factory(plugins={"gt": PROBE}, server_env_extra=SERVER_ENV)
    sid = rig.new_session()

    # (a) agent shell tool: both hooks, marked
    rig.prompt(sid, f"RUN {ENV_NAMES}")
    agent_names = set(str(rig.wait_results(1)[-1]["result"]).split())
    assert "AGENT" in agent_names

    # (b) subagent shell tool: both hooks, the agent id is the subagent's
    rig.prompt(sid, f"TASK RUN {ENV_NAMES}")
    rig.wait_results(3)
    before = names_of(rig, ev="execute.before")
    assert [(e["tool"], e["agent"]) for e in before] == [
        ("shell", "build"),
        ("subagent", "build"),
        ("shell", "general"),
    ]
    assert [e["marker"] for e in names_of(rig, ev="create.before")] == [True, True]

    # (c) the TUI's `!` (POST /api/session/:id/shell): create.before only, unmarked, no agent id
    n_before, n_create = len(before), len(names_of(rig, ev="create.before"))
    sid2 = rig.new_session()
    rig.bang(sid2, ENV_NAMES)
    deadline = time.time() + 10
    while len(names_of(rig, ev="create.before")) == n_create and time.time() < deadline:
        time.sleep(0.2)
    assert len(names_of(rig, ev="execute.before")) == n_before
    bang_create = names_of(rig, ev="create.before")[-1]
    assert bang_create["marker"] is False
    assert bang_create["timeout"] == 0
    time.sleep(0.5)
    shell_msgs = [
        m for m in rig.api("GET", f"/api/session/{sid2}/context")["data"] if m["type"] == "shell"
    ]
    bang_names = set(shell_msgs[0]["output"]["output"].split())
    assert "AGENT" not in bang_names
    assert "OPENCODE_SESSION_ID" not in bang_names
    assert "PROBE_HUMAN_TAG" in bang_names and "PROBE_AGENT_TAG" not in bang_names
    assert "PROBE_AGENT_TAG" in agent_names and "PROBE_HUMAN_TAG" not in agent_names

    # (d) an integrated PTY (POST /api/pty): no hook at all
    seen = len(events(rig))
    out = rig.logs / "pty-env.txt"
    rig.api(
        "POST",
        "/api/pty",
        {"command": "/bin/sh", "args": ["-c", f"env | cut -d= -f1 | sort > {out}; sleep 1"]},
    )
    deadline = time.time() + 10
    while not out.exists() and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(0.5)
    assert out.exists()
    assert len(events(rig)) == seen
    pty_names = set(out.read_text().split())
    assert "SSH_AUTH_SOCK" in pty_names  # not isolated: PTYs are outside the plugin's reach
    assert "AGENT" not in pty_names


def test_two_parallel_shell_calls_both_round_trip_with_one_nonce(rig_factory) -> None:
    rig = rig_factory(plugins={"gt": PROBE})
    sid = rig.new_session()
    rig.prompt(sid, "RUNPAR echo A ::: echo B")
    assert sorted(r["result"] for r in rig.wait_results(2)) == ["A\n", "B\n"]
    assert [e["marker"] for e in names_of(rig, ev="create.before")] == [True, True]


# --- Q6/Q7: runtime, timing, restart, hot reload ---------------------------------------------


def test_plugin_runtime_facts(rig_factory, real_opencode) -> None:
    rig = rig_factory(plugins={"gt": PROBE}, server_env_extra=SERVER_ENV)
    setup = names_of(rig, ev="setup")[0]
    assert setup["app"] == {
        "name": "cli",
        "version": real_opencode.version,
        "channel": setup["app"]["channel"],
    }
    assert setup["bun"] == "object"  # the plugin runs inside Bun
    assert setup["fs_ok"] and setup["child_process_ok"]
    assert setup["argv"][1] == "serve"
    assert (
        "OPENCODE_SERVER_PASSWORD" in setup["server_env_names"]
    )  # this rig sets one; real services have none
    assert setup["setup_ms"] < 100
    assert setup["process_uptime_s"] < 5  # loaded during start-up
    assert (
        sorted(setup["ctx_keys"]) == setup["ctx_keys"]
        and "shell" in setup["ctx_keys"]
        and "tool" in setup["ctx_keys"]
    )


def test_execute_before_to_create_before_takes_about_a_millisecond(rig_factory) -> None:
    rig = rig_factory(plugins={"gt": PROBE})
    for i in range(3):
        run_shell(rig, f"echo {i}")
    ev = events(rig)
    deltas = [
        b["p"] - a["p"]
        for a, b in zip(ev, ev[1:], strict=False)
        if a["ev"] == "execute.before" and b["ev"] == "create.before"
    ]
    assert len(deltas) == 3
    assert max(deltas) < 50  # ms; the self-test default of 2000 ms has a huge margin


def test_a_restart_runs_setup_again_with_a_fresh_nonce_and_hot_reload_swaps_the_plugin(
    rig_factory,
) -> None:
    rig = rig_factory(plugins={"s": hooky("s")})
    first = names_of(rig, ev="setup")[0]["nonce"]
    run_shell(rig, "echo one")
    plugin_file = rig.home / ".config/opencode/plugins/s/index.ts"
    plugin_file.write_text(
        plugin_file.read_text().replace('name: "s"', 'name: "s2"')
    )  # edit while running
    deadline = time.time() + 10
    while (
        not any(e.get("name") == "s2" for e in names_of(rig, ev="setup")) and time.time() < deadline
    ):
        time.sleep(0.3)
    setups = names_of(rig, ev="setup")
    assert [e["name"] for e in setups] == ["s", "s2"]  # the edit took effect without a restart
    assert setups[1]["nonce"] != first  # a reload is a new instance: the marker nonce changes
    assert any(e["ev"] == "cleanup" and e["name"] == "s" for e in events(rig))
    plugin_file.unlink()  # deleting it unloads G2 silently while the server keeps running
    time.sleep(3)
    seen = len(events(rig))
    assert run_shell(rig, "echo three").strip() == "three"
    assert [e["ev"] for e in events(rig)[seen:]] == []


# --- Q1 follow-up: what the `deny-edit-plugin` policy resource really covers -------------------


def test_edit_policy_for_plugins_dir_covers_nested_files_but_not_the_singular_plugin_dir(
    rig_factory,
) -> None:
    """``*`` spans ``/`` in a resource, so ``plugins/*`` guards ``plugins/carter/index.ts``.

    The singular ``plugin/`` directory is ALSO a plugin source (see above) and is not covered:
    an architect-gate item for the ``deny-edit-plugin`` statement (steps 8 and 26).
    """
    rig = rig_factory(
        extra_config={
            "policies": [
                {
                    "action": "tool.use",
                    "resource": "edit:*/.config/opencode/plugins/*",
                    "effect": "deny",
                }
            ]
        },
        extra_files={
            ".config/opencode/plugins/carter/index.ts": "// a\n",
            ".config/opencode/plugins/loose.txt": "// b\n",
            ".config/opencode/plugin/y.txt": "// c\n",
        },
    )
    sid = rig.new_session()

    def edit(target: Path) -> str:
        seen = len(rig.results())
        payload = {"path": str(target), "oldString": "//", "newString": "EDITED"}
        rig.prompt(sid, "CALL edit " + json.dumps(payload))
        return str(rig.wait_results(seen + 1)[-1]["result"])

    cfg = rig.home / ".config/opencode"
    for denied in (cfg / "plugins/carter/index.ts", cfg / "plugins/loose.txt"):
        assert "Blocked by configuration policy" in edit(denied)
        assert "EDITED" not in denied.read_text()
    assert "Edited" in edit(cfg / "plugin/y.txt")  # NOT blocked
    policies = [
        p for d in json.loads(rig.debug("config")) for p in d.get("info", {}).get("policies", [])
    ]
    assert {
        "action": "provider.use",
        "resource": "mock",
        "effect": "allow",
    } in policies  # providers survive


def test_execute_after_fires_for_completed_calls_only_never_for_a_rejected_call(
    rig_factory,
) -> None:
    """So a rejection cannot be told apart from a lost hook order by watching ``execute.after``."""
    late = (
        'import { Plugin } from "@opencode/plugin"\n'
        'export default Plugin.define({ id: "zz", setup(ctx: any) {\n'
        '  ctx.tool.hook("execute.before", (e: any) => {\n'
        '    if (String(e.input?.command).includes("LATE_REJECT")) throw new Error("late reject")\n'
        "  })\n"
        "} })\n"
    )
    rig = rig_factory(
        plugins={"gt": PROBE}, extra_files={".config/opencode/plugins/zz/index.ts": late}
    )
    for command in (
        "echo ok",
        "echo PROBE_THROW_EXEC",
        "echo PROBE_THROW_CREATE",
        "echo LATE_REJECT",
        "exit 3",
    ):
        run_shell(rig, command)
        time.sleep(0.3)
    after = names_of(rig, ev="execute.after")
    # `echo ok` and `exit 3` (a non-zero exit is still "completed"); nothing for the three rejected
    assert [e["status"] for e in after] == ["completed", "completed"]
