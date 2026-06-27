"""Parity tests — invariants that must hold across the dual agent sources.

Carter defines each agent twice: a static ``agents/carter-*.md`` (copied verbatim
by ``carter install``) and a ``templates/agents/carter-*.md.j2`` (rendered by
``carter init`` / ``carter update``). The two are hand-maintained, so byte-equality
of the bodies is intentionally NOT asserted here.

Instead these tests lock the *invariants* that must never drift between the two
sources — the security- and structure-critical contracts, including the YAML
frontmatter (``description``/``mode``) which both sources must emit identically
(ADR-0002). ``temperature`` is NOT emitted (ADR-0010 D7 — dead-or-rejected on every
model Carter pins; effort/temperature are runtime-owned). This is the phase-1
guardrail from docs/adr/0002-single-source-agent-generation.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from carter.config import (
    AGENT_MCP_SCOPE,
    RISK_TAXONOMY,
    effective_allowlist,
    generate_default_config,
)
from carter.scaffold import create_env, render_agents

# The seven redaction categories that must be present in BOTH narrator sources.
REDACTION_CATEGORIES = (
    "Secrets",
    "Internal URLs",
    "Security Incidents",
    "PII",
    "Financial Figures",
    "Employee Data",
    "Infrastructure IDs",
)


def _parse_frontmatter(text: str) -> dict:
    """Parse leading YAML frontmatter from an agent markdown file."""
    assert text.startswith("---\n"), "file does not start with '---' frontmatter"
    _, fm, _ = text.split("---", 2)
    return yaml.safe_load(fm)


@pytest.fixture
def static_agents_dir(repo_root: Path) -> Path:
    """Static agent sources copied by ``carter install``."""
    return repo_root / "agents"


@pytest.fixture
def template_agents_dir(repo_root: Path) -> Path:
    """Jinja agent templates rendered by ``carter init`` / ``update``."""
    return repo_root / "templates" / "agents"


class TestAgentSourceParity:
    """Both sources must describe the same set of agents."""

    def test_static_and_template_agent_sets_match(
        self, static_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        """Guards the ADR-0001 drift: the narrator once had a template but no
        static file, so ``carter install`` silently shipped 6 agents instead of 7.
        """
        static = {p.stem for p in static_agents_dir.glob("carter-*.md")}
        template = {
            p.name.removesuffix(".md.j2") for p in template_agents_dir.glob("carter-*.md.j2")
        }
        assert static == template, (
            f"Agent sources diverge — only static: {static - template}; "
            f"only template: {template - static}"
        )

    def test_static_agents_have_frontmatter(self, static_agents_dir: Path) -> None:
        """Static files must carry the YAML frontmatter the agent loaders need
        (this is the structural divergence the templates do not yet emit)."""
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            text = agent.read_text()
            assert text.startswith("---"), f"{agent.name} missing YAML frontmatter"
            assert "description:" in text, f"{agent.name} missing 'description:'"
            assert "mode:" in text, f"{agent.name} missing 'mode:'"

    def test_static_agents_have_ops_oneliner(self, static_agents_dir: Path) -> None:
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            text = agent.read_text()
            assert "ops:" in text and "carter-ops" in text, (
                f"{agent.name} missing the ops: one-liner"
            )


class TestNoRunSubagentFiction:
    """ADR-0010 D1/D8: ``runSubagent`` is a fiction — it exists on no target. It
    drifted back once before (the static maestro said ``runSubagent`` while the
    template said "chain sequentially", S3), so lock its absence across BOTH
    sources and the routing skill. Native dispatch (``agent``/``agents:``/
    ``permission.task``) is P3; here we only assert the fiction is gone.
    """

    def test_no_runsubagent_in_static_agents(self, static_agents_dir: Path) -> None:
        offenders = [
            p.name for p in sorted(static_agents_dir.glob("carter-*.md")) if "runSubagent" in p.read_text()
        ]
        assert not offenders, f"static agents still cite the runSubagent fiction: {offenders}"

    def test_no_runsubagent_in_agent_templates(self, template_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(template_agents_dir.glob("carter-*.md.j2"))
            if "runSubagent" in p.read_text()
        ]
        assert not offenders, f"agent templates still cite the runSubagent fiction: {offenders}"


class TestNoTemperatureEmission:
    """ADR-0010 D7: ``temperature`` is dropped wholesale — VS Code ignores it,
    OpenCode accepts it syntactically but every pinned Anthropic model rejects it
    at the API. Neither static source nor template may emit it in frontmatter.
    """

    def test_no_temperature_in_static_frontmatter(self, static_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(static_agents_dir.glob("carter-*.md"))
            if "temperature" in _parse_frontmatter(p.read_text())
        ]
        assert not offenders, f"static agents still emit temperature (ADR-0010 D7): {offenders}"

    def test_no_temperature_in_agent_templates(self, template_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(template_agents_dir.glob("carter-*.md.j2"))
            if "temperature:" in p.read_text()
        ]
        assert not offenders, f"agent templates still emit temperature (ADR-0010 D7): {offenders}"


class TestFleetContextRule:
    """ADR-0010 D1.D2: Copilot CLI ``/fleet`` subagents do NOT inherit chat history,
    so the maestro prose MUST instruct injecting the active-plan + knowledge context
    into every ``/fleet`` prompt — otherwise cross-domain runs silently lose Carter's
    state. Both the template and the static maestro must carry the rule.
    """

    def test_template_maestro_has_fleet_context_rule(self, template_agents_dir: Path) -> None:
        body = (template_agents_dir / "carter-maestro.md.j2").read_text()
        assert "/fleet" in body, "maestro template missing the /fleet orchestration rule"
        lower = body.lower()
        assert "do not inherit" in lower or "don't inherit" in lower or "inherit" in lower
        assert "active plan" in lower or "active-plan" in lower or "plan" in lower
        assert "knowledge" in lower

    def test_static_maestro_has_fleet_context_rule(self, static_agents_dir: Path) -> None:
        body = (static_agents_dir / "carter-maestro.md").read_text()
        assert "/fleet" in body, "static maestro missing the /fleet orchestration rule"
        lower = body.lower()
        assert "inherit" in lower
        assert "knowledge" in lower


class TestNarratorParity:
    """The narrator's security contract must be identical in spirit across sources."""

    def _both_sources(self, static_agents_dir: Path, template_agents_dir: Path) -> dict[str, str]:
        return {
            "static": (static_agents_dir / "carter-narrator.md").read_text(),
            "template": (template_agents_dir / "carter-narrator.md.j2").read_text(),
        }

    def test_redaction_invariants_in_both_sources(
        self, static_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, content in self._both_sources(static_agents_dir, template_agents_dir).items():
            assert "NON-NEGOTIABLE" in content, f"narrator {source}: missing NON-NEGOTIABLE"
            assert "Anti-Bypass" in content, f"narrator {source}: missing Anti-Bypass clause"
            for category in REDACTION_CATEGORIES:
                assert category in content, (
                    f"narrator {source}: missing redaction category '{category}'"
                )

    def test_reader_principle_in_both_sources(
        self, static_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, content in self._both_sources(static_agents_dir, template_agents_dir).items():
            assert "Write for the reader" in content, (
                f"narrator {source}: missing 'write for the reader' principle"
            )


class TestRenderedFrontmatterParity:
    """Templates must render install-ready frontmatter matching the static files.

    This is the ADR-0002 scaffold-bug fix: ``carter init`` previously produced
    agents with no frontmatter, dropping the ``description`` OpenCode requires and
    the ``mode`` the runtimes honor. ``temperature`` is dropped entirely (ADR-0010
    D7) — it must NOT appear in any emitted frontmatter.
    """

    def test_rendered_agents_have_valid_frontmatter(self) -> None:
        cfg = generate_default_config(workspace_name="parity", mode="single")
        rendered = render_agents(cfg, create_env())
        assert rendered, "no agents rendered"
        for name, content in rendered.items():
            fm = _parse_frontmatter(content)
            assert fm.get("description"), f"{name}: rendered without a description"
            assert fm.get("mode"), f"{name}: rendered without a mode"
            assert "temperature" not in fm, (
                f"{name}: emits temperature (dropped wholesale, ADR-0010 D7)"
            )

    def test_rendered_frontmatter_matches_static(self, static_agents_dir: Path) -> None:
        cfg = generate_default_config(workspace_name="parity", mode="single")
        cfg["agent_suffix"] = ""  # match canonical static filenames
        rendered = render_agents(cfg, create_env())
        for name, content in rendered.items():
            static = static_agents_dir / name
            assert static.exists(), f"no static counterpart for rendered {name}"
            assert _parse_frontmatter(content) == _parse_frontmatter(static.read_text()), (
                f"{name}: rendered frontmatter diverges from the static file"
            )

    def test_mode_vocabulary_is_valid_and_orchestrator_only(self, static_agents_dir: Path) -> None:
        """Pure-orchestrator model: maestro is the sole `primary`; every other
        agent is a `subagent`. All values must be valid OpenCode modes.
        """
        valid = {"primary", "subagent", "all"}
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            mode = _parse_frontmatter(agent.read_text())["mode"]
            assert mode in valid, f"{agent.name}: invalid mode '{mode}'"
            if agent.stem == "carter-maestro":
                assert mode == "primary", "maestro must be the primary orchestrator"
            else:
                assert mode == "subagent", (
                    f"{agent.name}: specialists must be 'subagent', got '{mode}'"
                )


class TestNoFalseReadOnlyClaim:
    """ADR-0005 D5: the shared full-scope MCP token makes a 'read-only' claim a
    false guarantee. Neither the static agents nor their templates may assert it
    in prose — actual tool scoping is enforced by the strictness-policy emission,
    not promised in the body. Closes the frontmatter-parity gap (RFC-0002 N3):
    the parity tests above check only frontmatter, so a body relapse would slip.
    """

    def test_no_static_agent_claims_read_only(self, static_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(static_agents_dir.glob("carter-*.md"))
            if "read-only" in p.read_text().lower()
        ]
        assert not offenders, (
            f"static agents still claim 'read-only' (false guarantee, ADR-0005 D5): {offenders}"
        )

    def test_no_agent_template_claims_read_only(self, template_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(template_agents_dir.glob("carter-*.md.j2"))
            if "read-only" in p.read_text().lower()
        ]
        assert not offenders, (
            f"agent templates still claim 'read-only' (false guarantee, ADR-0005 D5): {offenders}"
        )


class TestProseMatchesAllowlist:
    """The inverse of the read-only bug: an agent whose allowlist lacks
    ``remote-write`` must not claim 'Full access' in its Tool Access prose. On a
    non-enforcing target the advisory prose wins, so an over-claim would let a
    non-pusher remote-write — breaking the single-pusher invariant (only devops
    holds ``remote-write``). ADR-0005 D1/D4; ADR-0010 D4.
    """

    def test_non_pusher_agents_dont_claim_full_access(self, static_agents_dir: Path) -> None:
        allowlist = effective_allowlist(generate_default_config())
        offenders = []
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            role = agent.stem.removeprefix("carter-")
            holds_remote_write = allowlist.get(role, {}).get("remote-write", False)
            if not holds_remote_write and "full access" in agent.read_text().lower():
                offenders.append(agent.name)
        assert not offenders, (
            "non-pusher agents claim 'Full access' (prose over-claims remote-write the "
            f"allowlist denies, ADR-0005 D1/D4 / ADR-0010 D4): {offenders}"
        )


class TestStrictnessPolicyParity:
    """The baked ``policy:`` frontmatter in the global static agents (ADR-0005 D6)
    must match the shipped model. Statics carry the ``guarded`` defaults rendered
    at the default target (``copilot``); this is the N3-style dual-source guard —
    if the model changes but a static is not re-baked, this fails loudly.
    """

    def _role(self, agent_path: Path) -> str:
        return agent_path.stem.removeprefix("carter-")

    def test_static_agents_carry_policy_block(self, static_agents_dir: Path) -> None:
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            fm = _parse_frontmatter(agent.read_text())
            assert "policy" in fm, f"{agent.name}: missing baked policy block"
            assert "allow" in fm["policy"] and "gates" in fm["policy"], (
                f"{agent.name}: policy block missing allow/gates"
            )

    def test_static_allow_matches_shipped_allowlist(self, static_agents_dir: Path) -> None:
        allowlist = effective_allowlist(generate_default_config())
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            role = self._role(agent)
            fm = _parse_frontmatter(agent.read_text())
            expected = sorted(c for c, on in allowlist[role].items() if on)
            assert fm["policy"]["allow"] == expected, (
                f"{agent.name}: baked allow drifted from the shipped allowlist"
            )

    def test_static_gates_are_guarded(self, static_agents_dir: Path) -> None:
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            fm = _parse_frontmatter(agent.read_text())
            for cat, gate in fm["policy"]["gates"].items():
                assert gate == RISK_TAXONOMY[cat]["guarded"], (
                    f"{agent.name}: gate for {cat} is not the guarded value"
                )

    def test_static_tools_match_mcp_scope(self, static_agents_dir: Path) -> None:
        """Copilot is the default target, so statics carry ``tools`` (MCP scope)
        and never the OpenCode ``permission`` map. The maestro (primary) additionally
        carries the ``agent`` native-dispatch tool ahead of its MCP scope (ADR-0010 D1).
        """
        for agent in sorted(static_agents_dir.glob("carter-*.md")):
            role = self._role(agent)
            fm = _parse_frontmatter(agent.read_text())
            expected = [f"carter-{s}/*" for s in sorted(AGENT_MCP_SCOPE.get(role, []))]
            if role == "maestro":
                expected = ["agent", *expected]
            if expected:
                assert fm.get("tools") == expected, (
                    f"{agent.name}: baked tools drifted from the MCP scope"
                )
            else:
                assert "tools" not in fm, f"{agent.name}: unexpected tools for empty scope"
            assert "permission" not in fm, (
                f"{agent.name}: static (copilot default) must not bake opencode permission"
            )

    def test_static_maestro_carries_policy_gate_table(self, static_agents_dir: Path) -> None:
        """The global static maestro body must carry the always-on policy gate table
        (ADR-0005 D6) and the enforced `gate`-tier redaction handoff (ADR-0010 D5) —
        frontmatter parity can't catch a body relapse."""
        body = (static_agents_dir / "carter-maestro.md").read_text()
        assert "Strictness Policy" in body
        assert "remote-write" in body  # a 4-category taxonomy row is present
        assert "dangerous" in body
        # Enforced redaction handoff (no R6 overlay): substantive outward content
        # routes narrator -> devops as a gate-tier step.
        assert "gate`-tier redaction handoff" in body
        assert "carter-narrator" in body and "carter-devops" in body

    def test_static_narrator_carries_enforced_redaction_handoff(
        self, static_agents_dir: Path
    ) -> None:
        """The global static narrator body must wire the enforced author/transmit
        handoff (ADR-0010 D5) — narrator authors + redacts (gate-tier), devops
        transmits as the sole remote-write holder."""
        body = (static_agents_dir / "carter-narrator.md").read_text().lower()
        assert "transmit" in body
        assert "devops" in body
        assert "remote-write" in body  # narrator does NOT hold it; devops does
        assert "gate`-tier" in body
