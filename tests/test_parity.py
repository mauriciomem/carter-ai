"""Invariant tests for the agent templates and their rendered output.

Carter's agents have a single source, ``templates/agents/carter-*.md.j2``, rendered
by ``carter install`` (global, no suffix) and ``carter init`` / ``carter update``
(workspace). The static ``agents/`` tree was deleted in ADR-0014 phase 5; tests
that once checked it now check the rendered output (``rendered_agents_dir``).

These tests lock the security- and structure-critical contracts, including the
YAML frontmatter (``description``/``mode``) (ADR-0002). ``temperature`` is NOT
emitted (ADR-0010 D7 — dead-or-rejected on every model Carter pins;
effort/temperature are runtime-owned). This is the phase-1 guardrail from
ADR-0002 (single-source agent generation).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from carter.config import (
    effective_allowlist,
    generate_default_config,
    policy_native_keys,
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
    data: dict = yaml.safe_load(fm)
    return data


@pytest.fixture
def rendered_agents_dir(tmp_path: Path) -> Path:
    """Agents rendered from the templates with the default config — exactly what
    ``carter install`` / ``carter init`` write."""
    out = tmp_path / "rendered-agents"
    out.mkdir()
    cfg = generate_default_config()
    cfg["agent_suffix"] = ""  # as `carter install` renders the global agents
    for name, content in render_agents(cfg, create_env()).items():
        (out / name).write_text(content)
    return out


@pytest.fixture
def template_agents_dir(repo_root: Path) -> Path:
    """Jinja agent templates rendered by ``carter init`` / ``update``."""
    return repo_root / "templates" / "agents"


class TestAgentSourceParity:
    """Both sources must describe the same set of agents."""

    def test_rendered_and_template_agent_sets_match(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        """Guards the ADR-0001 drift: the narrator once had a template but no
        static file, so ``carter install`` silently shipped 6 agents instead of 7.
        """
        rendered = {p.stem for p in rendered_agents_dir.glob("carter-*.md")}
        template = {
            p.name.removesuffix(".md.j2") for p in template_agents_dir.glob("carter-*.md.j2")
        }
        assert rendered == template, (
            f"Agent sources diverge — only rendered: {rendered - template}; "
            f"only template: {template - rendered}"
        )

    def test_rendered_agents_have_frontmatter(self, rendered_agents_dir: Path) -> None:
        """Static files must carry the YAML frontmatter the agent loaders need
        (this is the structural divergence the templates do not yet emit)."""
        for agent in sorted(rendered_agents_dir.glob("carter-*.md")):
            text = agent.read_text()
            assert text.startswith("---"), f"{agent.name} missing YAML frontmatter"
            assert "description:" in text, f"{agent.name} missing 'description:'"
            assert "mode:" in text, f"{agent.name} missing 'mode:'"

    def test_rendered_agents_have_ops_oneliner(self, rendered_agents_dir: Path) -> None:
        for agent in sorted(rendered_agents_dir.glob("carter-*.md")):
            text = agent.read_text()
            assert "ops:" in text and "carter-ops" in text, (
                f"{agent.name} missing the ops: one-liner"
            )


class TestNoRunSubagentFiction:
    """``runSubagent`` is not a real tool; OpenCode dispatches through ``subagent``.
    It drifted back once before (the rendered maestro said ``runSubagent`` while the
    template said "chain sequentially"), so lock its absence in both the rendered
    agents (with and without a name suffix) and the templates.
    """

    @pytest.mark.parametrize("suffix", ["", "local"])
    def test_no_runsubagent_in_rendered_agents(self, suffix: str) -> None:
        cfg = generate_default_config()
        cfg["agent_suffix"] = suffix
        rendered = render_agents(cfg, create_env())
        assert rendered, "no agents rendered"
        offenders = [name for name, content in rendered.items() if "runSubagent" in content]
        assert not offenders, f"rendered agents still cite the runSubagent fiction: {offenders}"

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

    def test_no_temperature_in_rendered_frontmatter(self, rendered_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(rendered_agents_dir.glob("carter-*.md"))
            if "temperature" in _parse_frontmatter(p.read_text())
        ]
        assert not offenders, f"rendered agents still emit temperature (ADR-0010 D7): {offenders}"

    def test_no_temperature_in_agent_templates(self, template_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(template_agents_dir.glob("carter-*.md.j2"))
            if "temperature:" in p.read_text()
        ]
        assert not offenders, f"agent templates still emit temperature (ADR-0010 D7): {offenders}"


class TestSubagentContextRule:
    """ADR-0010 D1.D2 (kept under ADR-0014): delegated subagents do NOT inherit chat
    history, so the maestro must inline the active plan, relevant knowledge and the
    acceptance check into every delegated prompt. The Copilot ``/fleet`` wording is
    gone (ADR-0014 phase 5)."""

    def test_rendered_maestro_has_context_injection_rule(self, rendered_agents_dir: Path) -> None:
        lower = (rendered_agents_dir / "carter-maestro.md").read_text().lower()
        assert "do not inherit" in lower
        assert "active plan" in lower
        assert "knowledge" in lower
        assert "acceptance check" in lower

    def test_no_copilot_only_orchestration(self, rendered_agents_dir: Path) -> None:
        for agent in sorted(rendered_agents_dir.glob("carter-*.md")):
            text = agent.read_text()
            for marker in ("/fleet", "Copilot", "VS Code", "`agents:`", "`handoffs:`"):
                assert marker not in text, f"{agent.name} still carries {marker!r}"


# Skills each rendered agent must advertise (migrated from the deleted static
# ``agents/`` tree, ADR-0014 phase 5).
EXPECTED_SKILLS = {
    "architect": ("carter-design-review", "carter-diagram", "carter-adr", "carter-rfc"),
    "devops": (
        "carter-pipeline",
        "carter-terraform",
        "carter-packer",
        "carter-python",
        "carter-golang",
    ),
    "engineer": ("carter-code-review", "carter-test-first", "carter-python", "carter-golang"),
    "learner": ("carter-explain", "carter-mistakes", "carter-research"),
    "pm": ("carter-plan", "carter-risk"),
    "maestro": ("carter-ops", "carter-distill", "carter-reflect"),
    "narrator": ("carter-docs", "carter-story", "carter-atlassian", "carter-diagram"),
    "security": (
        "carter-threat-model",
        "carter-secure-review",
        "carter-vuln-triage",
        "carter-ir-runbook",
        "carter-pentest",
    ),
}

# MCP servers each rendered agent documents in its <mcp> Tool Access section.
EXPECTED_MCP = {
    "architect": ("carter-github", "carter-terraform"),
    "devops": ("carter-github", "carter-terraform"),
    "engineer": ("carter-github", "carter-terraform"),
    "learner": ("carter-atlassian",),
    "pm": ("carter-atlassian", "carter-github"),
    "security": ("carter-github",),
}


class TestMigratedAgentContent:
    @pytest.mark.parametrize("role", sorted(EXPECTED_SKILLS))
    def test_rendered_agent_lists_its_skills(self, rendered_agents_dir: Path, role: str) -> None:
        text = (rendered_agents_dir / f"carter-{role}.md").read_text()
        skills = text.split("<skills>", 1)[1].split("</skills>", 1)[0]
        for skill in EXPECTED_SKILLS[role]:
            assert f"`{skill}`" in skills, f"carter-{role} missing skill {skill}"

    def test_every_listed_skill_exists(self, repo_root: Path) -> None:
        shipped = {p.name for p in (repo_root / "skills").iterdir() if p.is_dir()}
        listed = {s for skills in EXPECTED_SKILLS.values() for s in skills}
        assert listed <= shipped, f"agents advertise unknown skills: {listed - shipped}"

    @pytest.mark.parametrize("role", sorted(EXPECTED_MCP))
    def test_rendered_agent_documents_mcp_access(
        self, rendered_agents_dir: Path, role: str
    ) -> None:
        text = (rendered_agents_dir / f"carter-{role}.md").read_text()
        mcp = text.split("<mcp>", 1)[1].split("</mcp>", 1)[0]
        for server in EXPECTED_MCP[role]:
            assert f"**{server}**" in mcp, f"carter-{role} <mcp> missing {server}"

    def test_maestro_routing_triggers(self, rendered_agents_dir: Path) -> None:
        text = (rendered_agents_dir / "carter-maestro.md").read_text()
        for trigger in ("kubernetes, vault, packer, hashicorp", "standup, WBS", "teach"):
            assert trigger in text


class TestMaestroInjectionGuard:
    """ADR-0011 non-regression: giving the maestro read tools means it now opens
    untrusted files directly, so its prompt-injection posture is MORE load-bearing.
    Both maestro sources MUST keep asserting that file contents are data to analyze,
    never instructions to act on (the stance the maestro correctly took when asked to
    "question everything" about an `ai-made` `prompt.md`). Both sources, so a re-bake
    or a template-only edit can't silently drop it.
    """

    def _both_maestros(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> dict[str, str]:
        return {
            "rendered": (rendered_agents_dir / "carter-maestro.md").read_text(),
            "template": (template_agents_dir / "carter-maestro.md.j2").read_text(),
        }

    def test_both_sources_assert_input_is_data_not_instructions(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, body in self._both_maestros(rendered_agents_dir, template_agents_dir).items():
            lower = body.lower()
            assert "data to analyze" in lower, (
                f"maestro {source}: missing the 'file contents are data' injection guard"
            )
            assert "never as instructions" in lower or "not as instructions" in lower, (
                f"maestro {source}: missing the 'never instructions to act on' clause"
            )


class TestSecurityAgentBoundaries:
    """The security agent reads the most attacker-controlled text, so its
    authorization posture and untrusted-input boundary are asserted over BOTH
    sources (rendered + template) as fixed-phrase greps — brittle-but-precise."""

    def _both(self, rendered_agents_dir: Path, template_agents_dir: Path) -> dict[str, str]:
        return {
            "rendered": (rendered_agents_dir / "carter-security.md").read_text(),
            "template": (template_agents_dir / "carter-security.md.j2").read_text(),
        }

    def test_authorization_posture_in_both_sources(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, body in self._both(rendered_agents_dir, template_agents_dir).items():
            lower = body.lower()
            assert "authorized" in lower, f"security {source}: missing 'authorized'"
            assert "refuse" in lower or "decline" in lower, f"security {source}: no refuse/decline"
            assert "destructive" in lower, f"security {source}: missing 'destructive'"
            assert "mass targeting" in lower, f"security {source}: missing 'mass targeting'"

    def test_untrusted_input_in_both_sources(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, body in self._both(rendered_agents_dir, template_agents_dir).items():
            lower = body.lower()
            assert "data to analyze" in lower, f"security {source}: missing untrusted-input guard"
            assert "never as instructions" in lower or "not as instructions" in lower, (
                f"security {source}: missing 'never instructions to act on'"
            )


class TestNarratorParity:
    """The narrator's security contract must be identical in spirit across sources."""

    def _both_sources(self, rendered_agents_dir: Path, template_agents_dir: Path) -> dict[str, str]:
        return {
            "rendered": (rendered_agents_dir / "carter-narrator.md").read_text(),
            "template": (template_agents_dir / "carter-narrator.md.j2").read_text(),
        }

    def test_redaction_invariants_in_both_sources(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, content in self._both_sources(rendered_agents_dir, template_agents_dir).items():
            assert "NON-NEGOTIABLE" in content, f"narrator {source}: missing NON-NEGOTIABLE"
            assert "Anti-Bypass" in content, f"narrator {source}: missing Anti-Bypass clause"
            for category in REDACTION_CATEGORIES:
                assert category in content, (
                    f"narrator {source}: missing redaction category '{category}'"
                )

    def test_reader_principle_in_both_sources(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, content in self._both_sources(rendered_agents_dir, template_agents_dir).items():
            assert "Write for the reader" in content, (
                f"narrator {source}: missing 'write for the reader' principle"
            )


class TestRenderedFrontmatterParity:
    """Templates must render install-ready frontmatter.

    ``carter init`` once produced agents with no frontmatter, dropping the
    ``description`` OpenCode requires and the ``mode`` the runtimes honor.
    """

    def test_rendered_frontmatter_is_v2_native(self) -> None:
        """Rendered frontmatter carries exactly the V2 keys Carter generates
        (``description``/``mode``/``model``/``permissions``): no V1 key (``permission``,
        ``tools``, ``temperature``…), no ``policy`` key, and no ``carter:policy``
        comment anywhere in the file."""
        cfg = generate_default_config(workspace_name="parity", mode="single")
        cfg["agent_suffix"] = ""
        rendered = render_agents(cfg, create_env())
        assert rendered, "no agents rendered"
        for name, content in rendered.items():
            role = name.removeprefix("carter-").removesuffix(".md")
            fm = _parse_frontmatter(content)
            assert set(fm) == {"description", "mode", "model", "permissions"}, name
            assert fm["description"], f"{name}: rendered without a description"
            assert isinstance(fm["permissions"], list) and fm["permissions"], name
            native = policy_native_keys(cfg, role)
            assert fm["permissions"] == native["permissions"], name
            assert fm["model"] == native["model"], name
            assert "carter:policy" not in content, name

    def test_mode_vocabulary_is_valid_and_orchestrator_only(
        self, rendered_agents_dir: Path
    ) -> None:
        """Pure-orchestrator model: maestro is the sole `primary`; every other
        agent is a `subagent`. All values must be valid OpenCode modes.
        """
        valid = {"primary", "subagent", "all"}
        for agent in sorted(rendered_agents_dir.glob("carter-*.md")):
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
    false guarantee. Neither the rendered agents nor their templates may assert it
    in prose — actual tool scoping is enforced by the strictness-policy emission,
    not promised in the body. Closes the frontmatter-parity gap:
    the parity tests above check only frontmatter, so a body relapse would slip.
    """

    def test_no_rendered_agent_claims_read_only(self, rendered_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(rendered_agents_dir.glob("carter-*.md"))
            if "read-only" in p.read_text().lower()
        ]
        assert not offenders, (
            f"rendered agents still claim 'read-only' (false guarantee, ADR-0005 D5): {offenders}"
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

    def test_non_pusher_agents_dont_claim_full_access(self, rendered_agents_dir: Path) -> None:
        allowlist = effective_allowlist(generate_default_config())
        offenders = []
        for agent in sorted(rendered_agents_dir.glob("carter-*.md")):
            role = agent.stem.removeprefix("carter-")
            holds_remote_write = allowlist.get(role, {}).get("remote-write", False)
            if not holds_remote_write and "full access" in agent.read_text().lower():
                offenders.append(agent.name)
        assert not offenders, (
            "non-pusher agents claim 'Full access' (prose over-claims remote-write the "
            f"allowlist denies, ADR-0005 D1/D4 / ADR-0010 D4): {offenders}"
        )


class TestRenderedBodyParity:
    """Body-prose invariants of the rendered agents (ADR-0005 D6 / ADR-0010 D5).
    The static tree's Copilot-shaped frontmatter is no longer checked (ADR-0014;
    the tree is deleted in a later phase)."""

    def test_rendered_maestro_carries_policy_gate_table(self, rendered_agents_dir: Path) -> None:
        """The global rendered maestro body must carry the always-on policy gate table
        (ADR-0005 D6) and the narrator -> devops redaction handoff (ADR-0010 D5;
        prompt-level per ADR-0014 D2) — frontmatter parity can't catch a body relapse."""
        body = (rendered_agents_dir / "carter-maestro.md").read_text()
        assert "Strictness Policy" in body
        assert "remote-write" in body  # a 4-category taxonomy row is present
        assert "dangerous" in body
        # Redaction handoff (no R6 overlay): substantive outward content routes
        # narrator -> devops. Prompt-level guidance, not harness-enforced (ADR-0014 D2).
        assert "redaction handoff" in body
        assert "gate`-tier" not in body
        assert "carter-narrator" in body and "carter-devops" in body

    def test_rendered_narrator_carries_redaction_handoff(self, rendered_agents_dir: Path) -> None:
        """The global rendered narrator body must wire the author/transmit
        handoff (ADR-0010 D5) — narrator authors + redacts, devops
        transmits as the sole remote-write holder."""
        body = (rendered_agents_dir / "carter-narrator.md").read_text().lower()
        assert "transmit" in body
        assert "devops" in body
        assert "remote-write" in body  # narrator does NOT hold it; devops does
        assert "redaction handoff" in body
        assert "gate`-tier" not in body  # not harness-enforced (ADR-0014 D2)


class TestTemplateRenderedBlockParity:
    """Every named content block a template defines must exist in the matching
    static file (ADR-0002 dual-source drift guard). Byte-equality is NOT asserted
    — section presence is. Drift class: rendered maestro shipped without
    session_bootstrap/quality_gate/knowledge_capture and rendered engineer without
    tdd_workflow while the templates had them (found 2026-08-01)."""

    # block name -> a literal marker string that must appear in the static file
    MAESTRO_BLOCKS = {
        "session_bootstrap": "<session_bootstrap>",
        "quality_gate": "<quality_gate>",
        "knowledge_capture": "<knowledge_capture>",
    }
    ENGINEER_BLOCKS = {"quality_gate": "<tdd_workflow>"}

    def test_rendered_maestro_carries_template_blocks(self, rendered_agents_dir):
        text = (rendered_agents_dir / "carter-maestro.md").read_text()
        for block, marker in self.MAESTRO_BLOCKS.items():
            assert marker in text, f"rendered maestro missing template block {block}"

    def test_rendered_engineer_carries_template_blocks(self, rendered_agents_dir):
        text = (rendered_agents_dir / "carter-engineer.md").read_text()
        for block, marker in self.ENGINEER_BLOCKS.items():
            assert marker in text, f"rendered engineer missing template block {block}"

    def test_rendered_maestro_carries_communication_block(self, rendered_agents_dir):
        """The dual-register communication block is MAESTRO-ONLY (maintainer
        decision D8, superseding D1-amended): the human-facing registers matter
        where a human is actually talking, and subagents keep the global baseline
        from the global AGENTS.md §Communication."""
        text = (rendered_agents_dir / "carter-maestro.md").read_text()
        assert "<communication>" in text, "rendered maestro missing the communication block"

    def test_rendered_subagents_do_not_carry_communication_block(self, rendered_agents_dir):
        """Inverse of the above — locks D8 so the block cannot silently drift back
        into the 7 subagents (it would cost ~570 tokens per subagent invocation)."""
        offenders = [
            p.name
            for p in sorted(rendered_agents_dir.glob("carter-*.md"))
            if p.stem != "carter-maestro" and "<communication>" in p.read_text()
        ]
        assert not offenders, f"communication block leaked into subagents (D8): {offenders}"

    def test_rendered_communication_block_is_maestro_only(self):
        """Same invariant over rendered output."""
        from carter.config import generate_default_config
        from carter.scaffold import create_env, render_agents

        cfg = generate_default_config(workspace_name="t", mode="single")
        cfg["agent_suffix"] = ""
        for name, content in render_agents(cfg, create_env()).items():
            has_block = "<communication>" in content
            if name == "carter-maestro.md":
                assert has_block, f"{name}: maestro rendered without the block"
            else:
                assert not has_block, f"{name}: block leaked into a subagent (D8)"
