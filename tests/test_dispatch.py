"""Tests for native subagent dispatch emission (P3, RFC-0005 §1 / ADR-0010 D1).

Carter emits the *real* per-target dispatch primitive on the primary (maestro) and
nowhere else, as an EXPLICIT per-specialist list (never ``'*'`` or a ``carter-*``
glob — a security boundary, D1.2):

- VS Code / Copilot: ``tools: ['agent']`` + ``agents: [carter-<role>, ...]`` + ``handoffs:``
- OpenCode: ``permission.task`` with ``'*': deny`` + a per-specialist ``allow`` entry
- specialists: ``agents: []`` (a flat, one-level chain — D1.3)

The emitted agent names honor ``agent_suffix`` so the dispatch allowlist references the
same suffixed files the rest of the agent body does (e.g. ``carter-engineer-local``).
"""

from __future__ import annotations

import yaml

from carter.config import generate_default_config, policy_frontmatter, policy_native_keys
from carter.scaffold import create_env, render_agents


def _config(target: str = "copilot", suffix: str = "") -> dict:
    cfg = generate_default_config(workspace_name="dispatch", mode="single")
    cfg["agent_suffix"] = suffix
    cfg["target"] = target
    return cfg


def _specialist_names(cfg: dict) -> list[str]:
    """The explicit per-specialist names (suffixed), sorted, maestro excluded."""
    raw = (cfg.get("agent_suffix") or "").strip()
    suffix = f"-{raw}" if raw else ""
    return sorted(f"carter-{a}{suffix}" for a in cfg["agents"] if a != "maestro")


# ─── Copilot / VS Code: agent tool + explicit agents: + handoffs: ────────────


class TestCopilotMaestroDispatch:
    def test_maestro_emits_agent_tool(self):
        keys = policy_native_keys(_config(target="copilot"), "maestro")
        assert "agent" in keys.get("tools", []), "maestro must enable the 'agent' subagent tool"

    def test_maestro_emits_explicit_agents_list(self):
        cfg = _config(target="copilot")
        keys = policy_native_keys(cfg, "maestro")
        assert keys.get("agents") == _specialist_names(cfg)
        assert "*" not in keys["agents"]
        assert not any("*" in a for a in keys["agents"]), "no glob in the agents list"

    def test_maestro_emits_handoffs(self):
        cfg = _config(target="copilot")
        keys = policy_native_keys(cfg, "maestro")
        assert keys.get("handoffs") == _specialist_names(cfg)

    def test_agents_list_honors_suffix(self):
        cfg = _config(target="copilot", suffix="local")
        keys = policy_native_keys(cfg, "maestro")
        assert "carter-engineer-local" in keys["agents"]
        assert "carter-engineer" not in keys["agents"]

    def test_specialists_emit_empty_agents_list(self):
        cfg = _config(target="copilot")
        for role in cfg["agents"]:
            if role == "maestro":
                continue
            keys = policy_native_keys(cfg, role)
            assert keys.get("agents") == [], f"{role}: specialists carry a flat agents: []"
            assert "handoffs" not in keys, f"{role}: only the primary emits handoffs"
            assert "agent" not in keys.get("tools", []), f"{role}: only the primary dispatches"


# ─── OpenCode: permission.task with explicit per-specialist allow ────────────


class TestOpencodeMaestroDispatch:
    def test_maestro_permission_task_denies_star(self):
        keys = policy_native_keys(_config(target="opencode"), "maestro")
        task = keys["permission"]["task"]
        assert task["*"] == "deny", "fail-closed: '*' must deny"

    def test_maestro_permission_task_allows_each_specialist(self):
        cfg = _config(target="opencode")
        task = policy_native_keys(cfg, "maestro")["permission"]["task"]
        for name in _specialist_names(cfg):
            assert task.get(name) == "allow", f"missing explicit allow for {name}"

    def test_permission_task_has_no_glob(self):
        cfg = _config(target="opencode")
        task = policy_native_keys(cfg, "maestro")["permission"]["task"]
        globs = [k for k in task if k != "*" and "*" in k]
        assert not globs, f"permission.task must be explicit per-specialist, not a glob: {globs}"

    def test_permission_task_honors_suffix(self):
        cfg = _config(target="opencode", suffix="local")
        task = policy_native_keys(cfg, "maestro")["permission"]["task"]
        assert task.get("carter-engineer-local") == "allow"
        assert "carter-engineer" not in task

    def test_specialists_emit_no_permission_task(self):
        cfg = _config(target="opencode")
        for role in cfg["agents"]:
            if role == "maestro":
                continue
            task = policy_native_keys(cfg, role)["permission"].get("task")
            assert task is None, f"{role}: only the primary emits permission.task"


# ─── Rendered frontmatter (end-to-end through render_agents + suffix pass) ────


class TestRenderedDispatchFrontmatter:
    def _maestro_fm(self, cfg: dict) -> dict:
        rendered = render_agents(cfg, create_env())
        suffix = (cfg.get("agent_suffix") or "").strip()
        name = f"carter-maestro{('-' + suffix) if suffix else ''}.md"
        text = rendered[name]
        _, fm, _ = text.split("---", 2)
        return yaml.safe_load(fm)

    def test_rendered_copilot_maestro_has_explicit_agents(self):
        cfg = _config(target="copilot", suffix="local")
        fm = self._maestro_fm(cfg)
        assert fm["agents"] == _specialist_names(cfg)
        assert "agent" in fm["tools"]
        assert fm["handoffs"] == _specialist_names(cfg)

    def test_rendered_opencode_maestro_has_explicit_task(self):
        cfg = _config(target="opencode", suffix="local")
        fm = self._maestro_fm(cfg)
        task = fm["permission"]["task"]
        assert task["*"] == "deny"
        assert task["carter-engineer-local"] == "allow"

    def test_no_runsubagent_fiction_anywhere(self):
        cfg = _config(target="all", suffix="local")
        for content in render_agents(cfg, create_env()).values():
            assert "runSubagent" not in content


# ─── policy_frontmatter carries the dispatch keys too (single source) ────────


class TestPolicyFrontmatterCarriesDispatch:
    def test_frontmatter_yaml_round_trips_dispatch_keys(self):
        cfg = _config(target="copilot")
        fm = yaml.safe_load(policy_frontmatter(cfg, "maestro"))
        assert "agents" in fm and "handoffs" in fm
        assert "agent" in fm["tools"]
