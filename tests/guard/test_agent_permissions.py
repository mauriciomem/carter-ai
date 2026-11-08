"""Per-agent ``carter_push`` denies for the built-in agents (D46, freeze F6; plan 003 step 12).
D72 removed ``carter_pr``; D70 removed the V1 ``agent.<n>.permission`` shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carter import harness
from carter.guard import policies
from carter.guard.state import GuardState
from carter.identity.policyset import Statement
from carter.install.mcp import config_target
from carter.install.paths import backups_dir

BUILTINS = ["build", "plan", "general", "explore"]
DENY_PUSH = {"action": "carter_push", "resource": "*", "effect": "deny"}
A = Statement("deny-a", "g2", "tool.use", "shell:aaa *", "deny", "t")


def dbg(stmts: list[Statement] = ()) -> str:  # type: ignore[assignment]
    items = [{"action": s.action, "resource": s.resource, "effect": s.effect} for s in stmts]
    return json.dumps({"providers": {"anthropic": {}}, "policies": items})


def agents_json(*ids: str) -> str:
    return json.dumps([{"id": i, "name": i} for i in ids])


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    return config_target(tmp_path)


def write_cfg(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def run(tmp_path: Path, state: GuardState, agents, stmts=(), **kw):
    return policies.apply(
        tmp_path, state, list(stmts), agents=agents, backup_root=backups_dir(tmp_path) / "t", **kw
    )


def read(cfg: Path) -> dict:
    return json.loads(cfg.read_text())


class TestDiscovery:
    def test_builtins_are_whatever_opencode_lists_that_is_not_carters(self, fake_opencode) -> None:
        fake_opencode(
            agents_output=agents_json("build", "plan", "carter-engineer", "carter-pm-local", "mine")
        )
        assert [i for i in harness.read_agent_ids() if not i.startswith("carter-")] == [
            "build",
            "plan",
            "mine",
        ]

    def test_failure_is_typed(self, fake_opencode) -> None:
        fake_opencode(agents_output="boom", agents_exit=1)
        with pytest.raises(harness.DebugConfigError):
            harness.read_agent_ids()

    def test_garbage_is_typed(self, fake_opencode) -> None:
        fake_opencode(agents_output="not json")
        with pytest.raises(harness.DebugConfigError):
            harness.read_agent_ids()

    def test_missing_opencode_is_typed(self) -> None:
        with pytest.raises(harness.DebugConfigError):
            harness.read_agent_ids(which=lambda _c: None)


class TestWrite:
    def test_builtins_get_the_deny_in_the_v2_shape_and_are_tracked(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        res = run(tmp_path, state, BUILTINS)
        agents = read(cfg)["agents"]
        for name in BUILTINS:
            assert agents[name]["permissions"] == [DENY_PUSH]
        assert res.perms.added == sorted(f"{n}:carter_push" for n in BUILTINS)
        assert len(state.agent_permissions) == 4
        rec = state.agent_permissions[0]
        assert rec == {
            "agent": "build",
            "key": "permission.carter_push",
            "value": "deny",
            "preexisting": False,
        }
        assert "policies" not in read(cfg)  # D46 is not a global policy

    def test_a_user_entry_is_merged_never_replaced(self, tmp_path, cfg, fake_opencode) -> None:
        mine = {"action": "edit", "resource": "*", "effect": "deny"}
        write_cfg(cfg, {"agents": {"plan": {"model": "x#high", "permissions": [mine]}}})
        fake_opencode(config_sequence=[dbg(), dbg()])
        run(tmp_path, GuardState(), ["plan"])
        entry = read(cfg)["agents"]["plan"]
        assert entry["model"] == "x#high"
        assert entry["permissions"] == [mine, DENY_PUSH]

    def test_other_agents_and_keys_are_untouched(self, tmp_path, cfg, fake_opencode) -> None:
        write_cfg(cfg, {"model": "m", "agents": {"title": {"model": "t"}}, "providers": {"a": {}}})
        fake_opencode(config_sequence=[dbg(), dbg()])
        run(tmp_path, GuardState(), ["build"])
        data = read(cfg)
        assert data["agents"]["title"] == {"model": "t"} and data["model"] == "m"

    def test_the_old_v1_map_is_not_handled_and_not_touched(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        """D70: no V1 shape. The deny always goes to ``agents.<name>.permissions``; a leftover
        ``agent.<name>.permission`` is the user's (``carter check --host`` names it)."""
        write_cfg(cfg, {"agent": {"plan": {"permission": {"edit": "deny"}}}})
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        run(tmp_path, state, ["plan", "build"])
        data = read(cfg)
        assert data["agent"]["plan"]["permission"] == {"edit": "deny"}
        assert data["agents"]["plan"]["permissions"] == [DENY_PUSH]
        assert data["agents"]["build"]["permissions"] == [DENY_PUSH]
        assert all("form" not in r for r in state.agent_permissions)

    @pytest.mark.parametrize(
        "bad",
        [{"agents": []}, {"agents": {"build": 1}}, {"agents": {"build": {"permissions": {}}}}],
    )
    def test_wrongly_shaped_containers_are_refused_and_untouched(
        self, tmp_path, cfg, fake_opencode, bad
    ) -> None:
        write_cfg(cfg, bad)
        before = cfg.read_bytes()
        fake_opencode(config_sequence=[dbg(), dbg()])
        with pytest.raises(policies.PolicyWriteError):
            run(tmp_path, GuardState(), ["build"])
        assert cfg.read_bytes() == before

    def test_an_identical_user_rule_is_preexisting(self, tmp_path, cfg, fake_opencode) -> None:
        write_cfg(cfg, {"agents": {"build": {"permissions": [DENY_PUSH]}}})
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        res = run(tmp_path, state, ["build"])
        assert read(cfg)["agents"]["build"]["permissions"] == [DENY_PUSH]
        assert res.perms.preexisting == ["build:carter_push"]
        flags = {r["key"]: r["preexisting"] for r in state.agent_permissions}
        assert flags == {"permission.carter_push": True}

    def test_idempotent_second_run_writes_nothing(self, tmp_path, cfg, fake_opencode) -> None:
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        run(tmp_path, state, BUILTINS)
        before = cfg.read_bytes()
        fake_opencode()
        res = run(tmp_path, state, BUILTINS)
        assert res.changed is False and cfg.read_bytes() == before

    def test_policies_and_permissions_are_one_write_one_verify(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        calls = {"n": 0}
        real = harness.read_debug_config

        def counting() -> dict:
            calls["n"] += 1
            return real()

        run(tmp_path, GuardState(), BUILTINS, stmts=[A], reader=counting)
        assert calls["n"] == 2  # before + after, once, for both kinds of edit
        assert read(cfg)["policies"] and read(cfg)["agents"]["build"]["permissions"]

    def test_a_dry_run_reports_and_writes_nothing(self, tmp_path, cfg, fake_opencode) -> None:
        fake_opencode()
        state = GuardState()
        res = run(tmp_path, state, BUILTINS, dry_run=True)
        assert res.changed and len(res.perms.added) == 4
        assert not cfg.exists() and state.agent_permissions == []

    def test_a_failed_verification_rolls_the_permissions_back_too(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        fake_opencode(config_sequence=[dbg(), dbg()])  # A is not loaded afterwards
        state = GuardState()
        with pytest.raises(Exception, match="deny-a"):
            run(tmp_path, state, BUILTINS, stmts=[A])
        assert not cfg.exists() and state.agent_permissions == []


class TestConverge:
    def test_an_agent_that_is_no_longer_listed_loses_its_denies(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        run(tmp_path, state, ["build", "plan"])
        fake_opencode(config_sequence=[dbg(), dbg()])
        res = run(tmp_path, state, ["build"])
        assert sorted(res.perms.removed) == ["plan:carter_push"]
        assert "plan" not in read(cfg)["agents"]
        assert {r["agent"] for r in state.agent_permissions} == {"build"}

    def test_an_earlier_carters_carter_pr_deny_is_taken_out_and_carter_push_stays(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        """D72 upgrade: the real host recorded both denies per agent."""
        old_pr = {"action": "carter_pr", "resource": "*", "effect": "deny"}
        write_cfg(cfg, {"agents": {"build": {"permissions": [DENY_PUSH, old_pr]}}})
        state = GuardState()
        state.record_permission("build", "permission.carter_push", "deny", preexisting=False)
        state.record_permission("build", "permission.carter_pr", "deny", preexisting=False)
        fake_opencode(config_sequence=[dbg(), dbg()])
        res = run(tmp_path, state, ["build"])
        assert read(cfg)["agents"]["build"]["permissions"] == [DENY_PUSH]
        assert res.perms.removed == ["build:carter_pr"]
        assert [r["key"] for r in state.agent_permissions] == ["permission.carter_push"]

    def test_g2_declined_later_means_no_agents_and_everything_is_removed(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        run(tmp_path, state, BUILTINS)
        fake_opencode(config_sequence=[dbg(), dbg()])
        run(tmp_path, state, [])
        assert "agents" not in read(cfg) and state.agent_permissions == []


class TestRemove:
    def install(self, tmp_path, fake_opencode, agents=BUILTINS):
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        run(tmp_path, state, agents)
        return state

    def remove(self, tmp_path, state):
        return policies.remove(tmp_path, state, backup_root=backups_dir(tmp_path) / "r")

    def test_removes_only_owned_unchanged_rules_and_prunes_what_it_emptied(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        mine = {"action": "edit", "resource": "*", "effect": "deny"}
        write_cfg(cfg, {"agents": {"plan": {"permissions": [mine]}, "title": {"model": "t"}}})
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        run(tmp_path, state, ["plan", "build"])
        fake_opencode(config_sequence=[dbg(), dbg()])
        res = self.remove(tmp_path, state)
        assert read(cfg) == {"agents": {"plan": {"permissions": [mine]}, "title": {"model": "t"}}}
        assert len(res.perms.removed) == 2 and state.agent_permissions == []

    def test_the_agents_map_disappears_when_carter_created_all_of_it(
        self, tmp_path, cfg, fake_opencode
    ) -> None:
        state = self.install(tmp_path, fake_opencode)
        fake_opencode(config_sequence=[dbg(), dbg()])
        self.remove(tmp_path, state)
        assert read(cfg) == {}

    def test_an_edited_rule_is_kept_and_reported(self, tmp_path, cfg, fake_opencode) -> None:
        state = self.install(tmp_path, fake_opencode, ["build"])
        data = read(cfg)
        data["agents"]["build"]["permissions"][0]["effect"] = "allow"  # the user flipped it
        write_cfg(cfg, data)
        fake_opencode(config_sequence=[dbg(), dbg()])
        res = self.remove(tmp_path, state)
        assert res.perms.kept_edited == ["build:carter_push"]
        assert read(cfg)["agents"]["build"]["permissions"] == [
            {"action": "carter_push", "resource": "*", "effect": "allow"}
        ]

    def test_preexisting_rules_are_never_removed(self, tmp_path, cfg, fake_opencode) -> None:
        write_cfg(cfg, {"agents": {"build": {"permissions": [DENY_PUSH]}}})
        fake_opencode(config_sequence=[dbg(), dbg()])
        state = GuardState()
        run(tmp_path, state, ["build"])
        fake_opencode(config_sequence=[dbg(), dbg()])
        self.remove(tmp_path, state)
        assert read(cfg)["agents"]["build"]["permissions"] == [DENY_PUSH]
