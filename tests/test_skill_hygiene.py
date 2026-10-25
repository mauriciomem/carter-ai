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
