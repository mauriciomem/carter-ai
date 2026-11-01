"""Skill sources carry only what OpenCode V2 reads."""

from __future__ import annotations

from pathlib import Path

import pytest

SKILLS = sorted((Path(__file__).resolve().parents[1] / "skills").glob("*/SKILL.md"))


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_frontmatter_has_no_argument_hint(skill: Path) -> None:
    # OpenCode V2 reads name/description/metadata only (opencode.ai/v2/docs/skills).
    frontmatter = skill.read_text().split("\n---", 1)[0]
    assert "argument-hint" not in frontmatter


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_no_platform_memory_or_harness_date(skill: Path) -> None:
    text = skill.read_text()
    assert " /memories/" not in text and "`/memories/`" not in text
    assert "harness date variable" not in text


# ─── Record templates carry ``ai-usage`` (RFC-0007 §4.2), plans do not carry push_policy ──

REPO = Path(__file__).resolve().parents[1]
AI_USAGE_LINE = "ai-usage: ai-assisted"


def _first_markdown_example(skill_name: str) -> str:
    """The first ```markdown fence of a skill: its record (frontmatter) template."""
    text = (REPO / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
    marker = "```markdown"
    start = text.index(marker) + len(marker)
    return text[start : text.index("```", start)].lstrip("\n")


def _frontmatter_of(example: str) -> str:
    assert example.startswith("---\n"), "template must open with a frontmatter block"
    return example.split("\n---", 1)[0]


class TestPlanSkillTemplate:
    def test_example_does_not_emit_push_policy(self) -> None:
        assert "push_policy" not in _frontmatter_of(_first_markdown_example("carter-plan"))

    def test_example_emits_ai_usage(self) -> None:
        assert AI_USAGE_LINE in _frontmatter_of(_first_markdown_example("carter-plan"))

    def test_example_documents_the_optional_enum(self) -> None:
        line = next(
            ln
            for ln in _frontmatter_of(_first_markdown_example("carter-plan")).splitlines()
            if ln.startswith("ai-usage:")
        )
        assert "ai-assisted | ai-generated | human-only" in line
        assert "optional" in line

    def test_skill_text_never_tells_the_pm_to_write_push_policy(self) -> None:
        text = (REPO / "skills" / "carter-plan" / "SKILL.md").read_text(encoding="utf-8")
        assert "push_policy" not in text


@pytest.mark.parametrize("skill_name", ["carter-adr", "carter-rfc", "carter-research"])
def test_record_template_carries_ai_usage(skill_name: str) -> None:
    assert AI_USAGE_LINE in _frontmatter_of(_first_markdown_example(skill_name))


def test_repo_docs_carry_no_front_matter() -> None:
    """RFC-0007 §4.2: repo docs (non-record) get no front matter."""
    docs = [REPO / "README.md", *sorted((REPO / "docs").rglob("*.md"))]
    local_only = (REPO / "docs" / "adr", REPO / "docs" / "rfcs")
    offenders = [
        str(p.relative_to(REPO))
        for p in docs
        if not any(d in p.parents for d in local_only)
        and p.read_text(encoding="utf-8").lstrip("\ufeff").startswith("---")
    ]
    assert offenders == []
