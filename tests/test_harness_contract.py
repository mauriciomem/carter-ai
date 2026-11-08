"""The `opencode debug config` / `debug agents` contract of OpenCode 2.1.4.

Recorded from the real binary in an isolated HOME (plan 003 step 26 spike; fixtures in
``tests/data/opencode-2.1.4-*.json``, all values made up). What the real thing does, as found:

- ``debug config`` prints a JSON **list of config sources**, not one merged object:
  ``{"type": "document", "path", "info": {...}}`` per config file (user scope; with cwd in a
  project also its ``opencode.jsonc``) and ``{"type": "directory", "path"}`` entries.
- A statement OpenCode rejects is **dropped silently** from ``info.policies`` (no stderr, no
  log line); the valid ones stay, in order. An invalid rule inside ``agents.<name>.permissions``
  drops that whole agent entry.
- A syntactically broken file yields **no document entry at all** (exit 0): everything in it,
  providers included, is gone.
- The first ``debug agents`` after the service starts can print ``[]``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from carter import harness

DATA = Path(__file__).resolve().parent / "data"
PUSH = {"action": "tool.use", "resource": "shell:git push *", "effect": "deny"}
SEND_PACK = {"action": "tool.use", "resource": "shell:git send-pack *", "effect": "deny"}


def fixture_text(name: str) -> str:
    return (DATA / f"opencode-2.1.4-{name}.json").read_text(encoding="utf-8")


def read(text: str, **kw):
    def runner(argv, **_kw):
        return subprocess.CompletedProcess(argv, 0, stdout=text, stderr="")

    return harness.read_debug_config(runner=runner, which=lambda _c: "/x/opencode", **kw)


class TestFixturesAreTheShapeWeDocument:
    def test_debug_config_is_a_list_of_sources(self) -> None:
        data = json.loads(fixture_text("debug-config"))
        assert isinstance(data, list)
        assert [e["type"] for e in data] == ["document", "directory"]
        assert set(data[0]) == {"type", "path", "info"} and set(data[1]) == {"type", "path"}
        assert {"policies", "providers", "agents"} <= set(data[0]["info"])

    def test_the_cold_agents_list_is_empty_and_the_warm_one_is_not(self) -> None:
        assert json.loads(fixture_text("debug-agents-cold")) == []
        warm = json.loads(fixture_text("debug-agents"))
        assert {"build", "plan", "general", "explore"} <= {a["id"] for a in warm}
        for agent in warm:
            assert {"id", "name", "request", "mode", "hidden", "permissions"} <= set(
                agent
            )  # `description` is optional
            assert isinstance(agent["permissions"], list)

    def test_a_per_agent_rule_lands_in_the_agent_permissions_before_openais_last_rule(self) -> None:
        warm = {a["id"]: a for a in json.loads(fixture_text("debug-agents"))}
        rule = {"action": "carter_push", "resource": "*", "effect": "deny"}
        assert rule in warm["build"]["permissions"]
        assert warm["build"]["permissions"][-1] == {
            "action": "browser",
            "resource": "*",
            "effect": "deny",
        }

    def test_no_fixture_holds_a_real_path_or_name(self) -> None:
        for path in DATA.glob("opencode-2.1.4-*.json"):
            text = path.read_text(encoding="utf-8")
            assert "/tmp/" not in text and "/home/gumbo" not in text, path.name


class TestListOfSources:
    def test_policies_providers_and_agents_are_merged(self) -> None:
        got = read(fixture_text("debug-config"))
        assert got["policies"] == [PUSH, SEND_PACK]
        assert harness.provider_ids(got) == {"example"}
        assert harness.policy_statements(got) == [PUSH, SEND_PACK]
        assert got["agents"]["build"]["permissions"] == [
            {"action": "carter_push", "resource": "*", "effect": "deny"}
        ]

    def test_project_documents_merge_after_the_user_document_in_source_order(self) -> None:
        got = read(fixture_text("debug-config-project"))
        assert harness.provider_ids(got) == {"example", "proj-only"}
        assert [s["resource"] for s in harness.policy_statements(got)] == [
            "shell:git push *",
            "shell:git send-pack *",
            "shell:git send-pack *",
        ]

    def test_rejected_statements_are_simply_not_there(self) -> None:
        got = read(fixture_text("debug-config-invalid-statements"))
        assert harness.policy_statements(got) == [PUSH, SEND_PACK]

    def test_a_broken_config_leaves_nothing_so_a_lost_provider_is_visible(self) -> None:
        got = read(fixture_text("debug-config-broken"))
        assert harness.provider_ids(got) == set()
        assert harness.policy_statements(got) == []
        before = harness.provider_ids(read(fixture_text("debug-config")))
        assert before - harness.provider_ids(got) == {"example"}

    def test_a_single_object_still_works(self) -> None:
        one = {"providers": {"acme": {}}, "policies": [PUSH]}
        assert read(json.dumps(one)) == one

    def test_unknown_source_types_are_ignored(self) -> None:
        data = [
            {"type": "remote", "path": "x"},
            {"type": "document", "path": "p", "info": {"providers": {"a": {}}}},
        ]
        assert harness.provider_ids(read(json.dumps(data))) == {"a"}

    def test_later_sources_extend_dict_blocks_and_override_scalars(self) -> None:
        data = [
            {
                "type": "document",
                "path": "1",
                "info": {"theme": "dark", "providers": {"a": {"x": 1}}},
            },
            {
                "type": "document",
                "path": "2",
                "info": {"theme": "light", "providers": {"a": {"y": 2}, "b": {}}},
            },
        ]
        got = read(json.dumps(data))
        assert got["theme"] == "light"
        assert got["providers"] == {"a": {"x": 1, "y": 2}, "b": {}}

    @pytest.mark.parametrize(
        "text",
        [
            "[]",
            "[1, 2]",
            '[{"path": "no type"}]',
            '[{"type": "document", "path": "p"}]',
            '[{"type": "document", "path": "p", "info": []}]',
            '[{"type": "document", "path": "p", "info": {"policies": "nope"}}]',
            "[null]",
            '"text"',
            "null",
            "",
            "not json",
        ],
    )
    def test_anything_else_fails_closed(self, text: str) -> None:
        with pytest.raises(harness.DebugConfigError):
            read(text)

    def test_an_error_never_quotes_the_output(self) -> None:
        secret = "sk-SENTINEL-provider-key-0123456789"
        text = json.dumps([{"type": "document", "path": secret, "info": {"policies": secret}}])
        with pytest.raises(harness.DebugConfigError) as exc:
            read(text)
        assert secret not in str(exc.value)


class TestAgentIdsRetryTheColdStart:
    def runner(self, outputs: list[str]):
        calls: list[int] = []

        def run(argv, **_kw):
            calls.append(1)
            out = outputs[min(len(calls), len(outputs)) - 1]
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

        return run, calls

    def test_an_empty_first_answer_is_retried_with_a_pause(self) -> None:
        run, calls = self.runner([fixture_text("debug-agents-cold"), fixture_text("debug-agents")])
        pauses: list[float] = []
        ids = harness.read_agent_ids(
            runner=run, which=lambda _c: "/x/opencode", sleep=pauses.append
        )
        assert "build" in ids and "carter-devops" in ids
        assert len(calls) == 2 and pauses == [0.5]

    def test_a_warm_answer_is_taken_at_once(self) -> None:
        run, calls = self.runner([fixture_text("debug-agents")])
        pauses: list[float] = []
        harness.read_agent_ids(runner=run, which=lambda _c: "/x/opencode", sleep=pauses.append)
        assert len(calls) == 1 and pauses == []

    def test_an_agent_list_that_stays_empty_is_an_error(self) -> None:
        run, calls = self.runner(["[]"])
        pauses: list[float] = []
        with pytest.raises(harness.DebugConfigError, match="no agents"):
            harness.read_agent_ids(runner=run, which=lambda _c: "/x/opencode", sleep=pauses.append)
        assert len(calls) == harness.DEFAULT_ATTEMPTS and pauses == [0.5, 1.0, 2.0, 4.0]

    def test_a_failing_call_is_not_retried(self) -> None:
        def run(argv, **_kw):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

        with pytest.raises(harness.DebugConfigError, match="exited 1"):
            harness.read_agent_ids(
                runner=run, which=lambda _c: "/x/opencode", sleep=lambda _s: None
            )


class TestPerAgentDeniesInDebugAgents:
    """What ``opencode debug agents`` carries once Carter's per-agent denies are installed.

    Plan 004 step 5 (spike D), recorded from the real 2.1.4 after ``carter install --yes`` in an
    isolated HOME (fixture ``debug-agents-denies``, trimmed, all values made up):

    - the rule ``{"action": "carter_push", "resource": "*", "effect": "deny"}`` is in
      the ``permissions`` of **14 of 15** agents: every built-in (build, plan, general, explore,
      compaction, summary, title) and every Carter agent except devops, which is exempt;
    - it sits just before OpenCode's last rule (``browser`` deny), so it is the last rule that
      matches ``carter_push`` (last match wins);
    - an agent whose ``agents.<name>`` entry holds one invalid rule loses the whole entry: it is
      then simply missing from ``debug config`` ``info.agents`` and from the effective rules
      (``debug-config-agent-dropped``), and OpenCode logs a ``configuration normalization
      diagnostic`` for ``$.agents.<name>`` with no rule detail.

    ``harness.agent_deny_gaps`` is what ``check --host`` uses (plan 004 step 30); the strict
    ``xfail`` markers written in step 5 were removed when it landed.
    """

    @staticmethod
    def agents() -> list[dict]:
        return json.loads(fixture_text("debug-agents-denies"))

    @staticmethod
    def gaps(agents: list[dict], **kw):
        return harness.agent_deny_gaps(agents, **kw)

    def test_the_fixture_has_the_denies_everywhere_but_devops(self) -> None:
        deny = {"carter_push": False}
        for agent in self.agents():
            rules = {(r["action"], r["resource"], r["effect"]) for r in agent["permissions"]}
            has = {a: (a, "*", "deny") in rules for a in deny}
            if agent["id"] == "carter-devops":
                assert not any(has.values())
            else:
                assert all(has.values()), agent["id"]
            assert agent["permissions"][-1]["action"] == "browser"

    def test_a_complete_install_has_no_gaps(self) -> None:
        assert self.gaps(self.agents(), exempt=("carter-devops",)) == []

    def test_a_missing_rule_names_the_agent_and_the_action(self) -> None:
        agents = self.agents()
        build = next(a for a in agents if a["id"] == "build")
        build["permissions"] = [r for r in build["permissions"] if r["action"] != "carter_push"]
        assert self.gaps(agents, exempt=("carter-devops",)) == [("build", "carter_push")]

    def test_the_last_matching_rule_wins_so_a_later_allow_is_a_gap(self) -> None:
        agents = self.agents()
        plan = next(a for a in agents if a["id"] == "plan")
        plan["permissions"].append({"action": "carter_*", "resource": "*", "effect": "allow"})
        assert self.gaps(agents, exempt=("carter-devops",)) == [
            ("plan", "carter_push"),
        ]

    def test_devops_is_a_gap_unless_it_is_exempt(self) -> None:
        assert self.gaps(self.agents(), exempt=()) == [
            ("carter-devops", "carter_push"),
        ]

    def test_a_dropped_agent_entry_is_visible_in_debug_config(self) -> None:
        sources = json.loads(fixture_text("debug-config-agent-dropped"))
        merged = harness._resolve(sources)  # the reader's merge, reused
        assert set(merged["agents"]) == {"plan"}  # `build` was written but is gone
