"""Invariant tests for the agent templates and their rendered output.

Carter's agents have a single source, ``templates/agents/carter-*.md.j2``, rendered
by ``carter install`` (global, no suffix) and ``carter init`` / ``carter update``
(workspace). There is no static agent tree; tests check the rendered output
(``rendered_agents_dir``) and the templates.

These tests lock the security- and structure-critical contracts, including the
YAML frontmatter (``description``/``mode``). ``temperature`` is NOT emitted (it is
ignored or rejected by every model Carter pins; effort/temperature are
runtime-owned).
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
    # Every per-agent loop below would pass vacuously over an empty directory.
    assert any(out.glob("carter-*.md")), "no agents rendered"
    return out


@pytest.fixture
def template_agents_dir(repo_root: Path) -> Path:
    """Jinja agent templates rendered by ``carter init`` / ``update``."""
    path = repo_root / "templates" / "agents"
    assert any(path.glob("carter-*.md.j2")), f"no agent templates in {path}"
    return path


class TestAgentSourceParity:
    """Both sources must describe the same set of agents."""

    def test_rendered_and_template_agent_sets_match(
        self, rendered_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        """Guards a past drift: the narrator once had a template but no
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


class TestNoTemperatureEmission:
    """``temperature`` is dropped wholesale — OpenCode accepts it syntactically but
    every pinned Anthropic model rejects it at the API. Neither rendered agents nor
    templates may emit it in frontmatter.
    """

    def test_no_temperature_in_rendered_frontmatter(self, rendered_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(rendered_agents_dir.glob("carter-*.md"))
            if "temperature" in _parse_frontmatter(p.read_text())
        ]
        assert not offenders, f"rendered agents still emit temperature: {offenders}"

    def test_no_temperature_in_agent_templates(self, template_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(template_agents_dir.glob("carter-*.md.j2"))
            if "temperature:" in p.read_text()
        ]
        assert not offenders, f"agent templates still emit temperature: {offenders}"


class TestSubagentContextRule:
    """Delegated subagents do NOT inherit chat history, so the maestro must inline
    the active plan, relevant knowledge and the acceptance check into every
    delegated prompt."""

    def test_rendered_maestro_has_context_injection_rule(self, rendered_agents_dir: Path) -> None:
        lower = (rendered_agents_dir / "carter-maestro.md").read_text().lower()
        assert "do not inherit" in lower
        assert "active plan" in lower
        assert "knowledge" in lower
        assert "acceptance check" in lower


# Skills each rendered agent must advertise.
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
    """Non-regression: giving the maestro read tools means it now opens
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
    """The shared full-scope MCP token makes a 'read-only' claim a
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
            f"rendered agents still claim 'read-only' (false guarantee): {offenders}"
        )

    def test_no_agent_template_claims_read_only(self, template_agents_dir: Path) -> None:
        offenders = [
            p.name
            for p in sorted(template_agents_dir.glob("carter-*.md.j2"))
            if "read-only" in p.read_text().lower()
        ]
        assert not offenders, (
            f"agent templates still claim 'read-only' (false guarantee): {offenders}"
        )


class TestNoAgentPushes:
    """Plan 003 step 12 (T14): no agent pushes; devops is the sole caller of B.

    Structural half: the rendered frontmatter of every Carter agent. The prose half (the
    devops template no longer claims it pushes) lands with step 23, so this step ends green.
    """

    PUSH_VERBS = ("git push", "gh pr create", "gh pr merge", "gh api", "gh release")

    @staticmethod
    def _rules(rendered_agents_dir: Path) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for agent in sorted(rendered_agents_dir.glob("carter-*.md")):
            out[agent.stem.removeprefix("carter-")] = _parse_frontmatter(agent.read_text())[
                "permissions"
            ]
        assert out
        return out

    def test_no_agent_has_a_push_allow_or_ask(self, rendered_agents_dir: Path) -> None:
        offenders = []
        for role, rules in self._rules(rendered_agents_dir).items():
            for rule in rules:
                if rule["action"] != "shell" or not rule["resource"].startswith(self.PUSH_VERBS):
                    continue
                # `git push --force *` is a dangerous-category gate, but a later plain
                # `git push *` deny wins (last match), so check the effective verdict.
                verdict = [
                    r["effect"]
                    for r in rules
                    if r["action"] == "shell" and r["resource"] == "git push *"
                ][-1]
                if rule["resource"] == "git push --force *":
                    assert verdict == "deny", role
                elif rule["effect"] != "deny":
                    offenders.append((role, rule["resource"], rule["effect"]))
        assert not offenders, f"agents can still push or write to GitHub: {offenders}"

    def test_only_devops_lacks_the_carter_broker_deny(self, rendered_agents_dir: Path) -> None:
        for role, rules in self._rules(rendered_agents_dir).items():
            denies = {r["action"] for r in rules if r["effect"] == "deny"}
            has_both = {"carter_push", "carter_pr"} <= denies
            assert has_both is (role != "devops"), role
            if role == "devops":
                assert not {r["action"] for r in rules} & {"carter_push", "carter_pr"}

    def test_the_broker_denies_come_from_the_data_file(self, rendered_agents_dir: Path) -> None:
        from carter.identity.policyset import agent_permission_denies, agent_permission_exempt

        rules = self._rules(rendered_agents_dir)
        for role, agent_rules in rules.items():
            expected = [] if role in agent_permission_exempt() else list(agent_permission_denies())
            got = [r["action"] for r in agent_rules if r["action"] in agent_permission_denies()]
            assert got == expected, role

    def test_the_global_policy_set_never_names_the_broker_tools(self) -> None:
        # D46 is per-agent: a global deny would block devops as well.
        from carter.identity.policyset import policy_set

        assert not [s for s in policy_set() if "carter_" in s.resource]


class TestProseMatchesAllowlist:
    """The inverse of the read-only bug: an agent whose allowlist lacks
    ``remote-write`` must not claim 'Full access' in its Tool Access prose. On a
    non-enforcing harness the advisory prose wins, so an over-claim would let an
    agent without ``remote-write`` write remotely — breaking the sole-holder invariant
    (only devops holds ``remote-write``).
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
            f"allowlist denies): {offenders}"
        )


class TestRenderedBodyParity:
    """Body-prose invariants of the rendered agents."""

    def test_rendered_maestro_carries_policy_gate_table(self, rendered_agents_dir: Path) -> None:
        """The global rendered maestro body must carry the always-on policy gate table
        and the narrator -> devops redaction handoff (prompt-level guidance) —
        frontmatter parity can't catch a body relapse."""
        body = (rendered_agents_dir / "carter-maestro.md").read_text()
        assert "Strictness Policy" in body
        assert "remote-write" in body  # a 4-category taxonomy row is present
        assert "dangerous" in body
        # Redaction handoff (no R6 overlay): substantive outward content routes
        # narrator -> devops. Prompt-level guidance, not harness-enforced.
        assert "redaction handoff" in body
        assert "gate`-tier" not in body
        assert "carter-narrator" in body and "carter-devops" in body

    def test_rendered_narrator_carries_redaction_handoff(self, rendered_agents_dir: Path) -> None:
        """The global rendered narrator body must wire the author/transmit
        handoff — narrator authors + redacts, devops
        transmits as the sole remote-write holder."""
        body = (rendered_agents_dir / "carter-narrator.md").read_text().lower()
        assert "transmit" in body
        assert "devops" in body
        assert "remote-write" in body  # narrator does NOT hold it; devops does
        assert "redaction handoff" in body
        assert "gate`-tier" not in body  # not harness-enforced


class TestTemplateRenderedBlockParity:
    """Every named content block a template defines must exist in the rendered
    agent. Byte-equality is NOT asserted
    — section presence is. Drift class: rendered maestro shipped without
    session_bootstrap/quality_gate/knowledge_capture and rendered engineer without
    tdd_workflow while the templates had them (found 2026-08-01)."""

    # block name -> a literal marker string that must appear in the rendered agent
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
        """The dual-register communication block is MAESTRO-ONLY (a maintainer
        decision): the human-facing registers matter
        where a human is actually talking, and subagents keep the global baseline
        from the global AGENTS.md §Communication."""
        text = (rendered_agents_dir / "carter-maestro.md").read_text()
        assert "<communication>" in text, "rendered maestro missing the communication block"

    def test_rendered_subagents_do_not_carry_communication_block(self, rendered_agents_dir):
        """Inverse of the above — locks the decision so the block cannot silently drift back
        into the 7 subagents (it would cost ~570 tokens per subagent invocation)."""
        offenders = [
            p.name
            for p in sorted(rendered_agents_dir.glob("carter-*.md"))
            if p.stem != "carter-maestro" and "<communication>" in p.read_text()
        ]
        assert not offenders, f"communication block leaked into subagents: {offenders}"

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
                assert not has_block, f"{name}: block leaked into a subagent"


class TestCarterOpsSkillGeneratedBlocks:
    """The forbidden list and error table inside the carter-ops skill are rendered from
    ``g2_rules.json`` and ``errors.json``; hand edits (drift) fail here with the expected
    block. Refresh with ``python -m carter.identity.blocks skills/carter-ops/SKILL.md``."""

    SKILL = Path(__file__).resolve().parent.parent / "skills" / "carter-ops" / "SKILL.md"

    def test_skill_blocks_equal_their_data_files(self) -> None:
        from carter.identity.blocks import check_text

        problems = check_text(self.SKILL.read_text(encoding="utf-8"))
        assert not problems, "\n\n".join(problems)

    def test_a_hand_edited_block_is_reported_with_the_expected_rendering(self) -> None:
        from carter.identity.blocks import check_text
        from carter.identity.rules import render_forbidden_block

        text = self.SKILL.read_text(encoding="utf-8").replace("`--no-verify`", "`--nope`")
        problems = check_text(text)
        assert any(p.startswith("forbidden: block differs") for p in problems)
        assert render_forbidden_block() in "\n".join(problems)

    def test_missing_markers_are_reported(self) -> None:
        from carter.identity.blocks import check_text

        assert len(check_text("no markers here")) == 2

    def test_sync_repairs_a_drifted_file(self) -> None:
        from carter.identity.blocks import check_text, sync_text

        text = self.SKILL.read_text(encoding="utf-8").replace("`--no-verify`", "`--nope`")
        assert check_text(sync_text(text)) == []

    def test_sync_is_idempotent(self) -> None:
        from carter.identity.blocks import sync_text

        text = self.SKILL.read_text(encoding="utf-8")
        assert sync_text(sync_text(text)) == sync_text(text)


class TestHandoffProse:
    """Plan 003 step 23 (T14, text half): the agent-facing prose matches the push model.

    Nobody pushes. A finished branch is a handoff file, then the human runs ``carter push`` and
    ``carter pr``. Jira and Slack stay with devops. The one sentence about *where* comes from
    ``handoff.OWN_TERMINAL`` and nowhere else."""

    @staticmethod
    def _body(rendered_agents_dir: Path, role: str) -> str:
        """The prose after the frontmatter (the permission rules legitimately name `git push`)."""
        text = (rendered_agents_dir / f"carter-{role}.md").read_text()
        return " ".join(text.split("\n---\n", 1)[1].split())

    def test_devops_describes_the_handoff_and_no_longer_pushes(
        self, rendered_agents_dir: Path
    ) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        body = self._body(rendered_agents_dir, "devops")
        assert OWN_TERMINAL in body
        assert ".carter/state/handoff/<encoded-branch>.md" in body and "`carter-ops`" in body
        assert "`carter push`" in body and "`carter pr`" in body  # as the human's commands
        assert "Jira and Slack writes stay with you" in body
        assert "Pushing and GitHub writes are human-only" in body
        for gone in ("git push", "gh pr create", "gh pr merge", "Full access — create PRs"):
            assert gone not in body, gone
        assert "single pusher" not in body and "sole pusher" not in body.lower()

    def test_devops_says_a_broker_may_come_but_does_not_name_tools_as_usable(
        self, rendered_agents_dir: Path
    ) -> None:
        body = self._body(rendered_agents_dir, "devops")
        assert "later release" in body and "do not look for them or try them" in body
        assert "carter_push" not in body and "carter_pr" not in body

    @pytest.mark.parametrize("role", ["engineer", "maestro", "pm", "security", "narrator"])
    def test_other_agents_route_pushing_to_the_handoff(
        self, rendered_agents_dir: Path, role: str
    ) -> None:
        body = self._body(rendered_agents_dir, role)
        assert "human-only" in body, role
        assert "single pusher" not in body and "Only devops can push" not in body
        assert "sole holder of `remote-write` and `dangerous` — the single" not in body

    def test_engineer_and_maestro_hand_the_branch_to_devops_for_the_handoff_file(
        self, rendered_agents_dir: Path
    ) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        engineer = self._body(rendered_agents_dir, "engineer")
        assert "carter-devops" in engineer and "handoff file" in engineer
        assert "`carter push` and `carter pr`" in engineer
        maestro = self._body(rendered_agents_dir, "maestro")
        assert OWN_TERMINAL in maestro and "handoff file" in maestro
        assert "carter-devops" in maestro and "Jira and Slack" in maestro

    def test_the_narrator_transmits_nothing_to_github(self, rendered_agents_dir: Path) -> None:
        body = self._body(rendered_agents_dir, "narrator")
        assert "Nobody transmits to GitHub" in body
        assert "redaction handoff" in body and "remote-write" in body and "transmit" in body

    def test_denied_roles_do_not_claim_the_github_mcp(self, rendered_agents_dir: Path) -> None:
        from carter.identity.policyset import agent_mcp_denies

        action, roles = agent_mcp_denies()
        assert roles  # the data names at least one role
        for role in roles:
            text = (rendered_agents_dir / f"carter-{role}.md").read_text()
            frontmatter = _parse_frontmatter(text)["permissions"]
            assert {"action": action, "resource": "*", "effect": "deny"} in frontmatter
            tool_access = text.split("## Tool Access", 1)[1]
            assert "carter-github" in tool_access, role
            line = next(ln for ln in tool_access.splitlines() if "carter-github" in ln)
            assert "Not available to you" in line, role

    def test_roles_that_keep_the_github_mcp_describe_it_as_reads(
        self, rendered_agents_dir: Path
    ) -> None:
        from carter.identity.policyset import agent_mcp_denies

        _, denied = agent_mcp_denies()
        for agent in sorted(rendered_agents_dir.glob("carter-*.md")):
            role = agent.stem.removeprefix("carter-")
            text = agent.read_text()
            if role in denied or "**carter-github**" not in text:
                continue
            line = next(ln for ln in text.splitlines() if "**carter-github**" in ln)
            assert "full access" not in line.lower(), role
