"""Parity tests — invariants that must hold across the dual agent sources.

Carter defines each agent twice: a static ``agents/carter-*.md`` (copied verbatim
by ``carter install``) and a ``templates/agents/carter-*.md.j2`` (rendered by
``carter init`` / ``carter update``). The two are hand-maintained, so byte-equality
of the bodies is intentionally NOT asserted here.

Instead these tests lock the *invariants* that must never drift between the two
sources — the security- and structure-critical contracts, including the YAML
frontmatter (``description``/``mode``/``temperature``) which both sources must now
emit identically (ADR-0002). This is the phase-1 guardrail from
docs/adr/0002-single-source-agent-generation.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from carter.config import generate_default_config
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


class TestNarratorParity:
    """The narrator's security contract must be identical in spirit across sources."""

    def _both_sources(
        self, static_agents_dir: Path, template_agents_dir: Path
    ) -> dict[str, str]:
        return {
            "static": (static_agents_dir / "carter-narrator.md").read_text(),
            "template": (template_agents_dir / "carter-narrator.md.j2").read_text(),
        }

    def test_redaction_invariants_in_both_sources(
        self, static_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, content in self._both_sources(
            static_agents_dir, template_agents_dir
        ).items():
            assert "NON-NEGOTIABLE" in content, f"narrator {source}: missing NON-NEGOTIABLE"
            assert "Anti-Bypass" in content, f"narrator {source}: missing Anti-Bypass clause"
            for category in REDACTION_CATEGORIES:
                assert category in content, (
                    f"narrator {source}: missing redaction category '{category}'"
                )

    def test_reader_principle_in_both_sources(
        self, static_agents_dir: Path, template_agents_dir: Path
    ) -> None:
        for source, content in self._both_sources(
            static_agents_dir, template_agents_dir
        ).items():
            assert "Write for the reader" in content, (
                f"narrator {source}: missing 'write for the reader' principle"
            )


class TestRenderedFrontmatterParity:
    """Templates must render install-ready frontmatter matching the static files.

    This is the ADR-0002 scaffold-bug fix: ``carter init`` previously produced
    agents with no frontmatter, dropping the ``description`` OpenCode requires and
    the ``mode``/``temperature`` the runtimes honor.
    """

    def test_rendered_agents_have_valid_frontmatter(self) -> None:
        cfg = generate_default_config(workspace_name="parity", mode="single")
        rendered = render_agents(cfg, create_env())
        assert rendered, "no agents rendered"
        for name, content in rendered.items():
            fm = _parse_frontmatter(content)
            assert fm.get("description"), f"{name}: rendered without a description"
            assert fm.get("mode"), f"{name}: rendered without a mode"
            assert isinstance(
                fm.get("temperature"), (int, float)
            ), f"{name}: rendered without a numeric temperature"

    def test_rendered_frontmatter_matches_static(
        self, static_agents_dir: Path
    ) -> None:
        cfg = generate_default_config(workspace_name="parity", mode="single")
        cfg["agent_suffix"] = ""  # match canonical static filenames
        rendered = render_agents(cfg, create_env())
        for name, content in rendered.items():
            static = static_agents_dir / name
            assert static.exists(), f"no static counterpart for rendered {name}"
            assert _parse_frontmatter(content) == _parse_frontmatter(
                static.read_text()
            ), f"{name}: rendered frontmatter diverges from the static file"

    def test_mode_vocabulary_is_valid_and_orchestrator_only(
        self, static_agents_dir: Path
    ) -> None:
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
            "static agents still claim 'read-only' (false guarantee, ADR-0005 D5): "
            f"{offenders}"
        )

    def test_no_agent_template_claims_read_only(
        self, template_agents_dir: Path
    ) -> None:
        offenders = [
            p.name
            for p in sorted(template_agents_dir.glob("carter-*.md.j2"))
            if "read-only" in p.read_text().lower()
        ]
        assert not offenders, (
            "agent templates still claim 'read-only' (false guarantee, ADR-0005 D5): "
            f"{offenders}"
        )

