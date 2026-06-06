"""Parity tests — invariants that must hold across the dual agent sources.

Carter defines each agent twice: a static ``agents/carter-*.md`` (copied verbatim
by ``carter install``) and a ``templates/agents/carter-*.md.j2`` (rendered by
``carter init`` / ``carter update``). The two are hand-maintained and have
diverged structurally (the static files carry YAML frontmatter; the templates do
not), so byte-equality is intentionally NOT asserted here.

Instead these tests lock the *invariants* that must never drift between the two
sources — the security- and structure-critical contracts. This is the phase-1
guardrail from docs/adr/0002-single-source-agent-generation.md (build-time
generation is deferred until the sources are reconciled).
"""
from __future__ import annotations

from pathlib import Path

import pytest

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
