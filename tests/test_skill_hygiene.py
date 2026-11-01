"""Skill sources carry only what OpenCode V2 reads."""

from __future__ import annotations

import re
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


# ─── carter-ops: the agent commit recipe (plan 002 step 15) ───

OPS_SKILL = REPO / "skills" / "carter-ops" / "SKILL.md"


def _ops_text() -> str:
    return OPS_SKILL.read_text(encoding="utf-8")


def _code_fences(text: str) -> list[str]:
    return re.findall(r"```[a-z]*\n(.*?)```", text, flags=re.S)


class TestCarterOpsRecipe:
    def test_no_identity_placeholders_are_left_in_any_skill_or_template(self) -> None:
        offenders = [
            str(p.relative_to(REPO))
            for root in ("skills", "templates")
            for p in (REPO / root).rglob("*")
            if p.is_file() and re.search(r"\{\{(BOT_|SIGNING_KEY)", p.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    def test_recipe_never_signs(self) -> None:
        for fence in _code_fences(_ops_text()):
            assert not re.search(r"git commit\b[^\n]*(?:\s-S|--gpg-sign|\s-s\b|--signoff)", fence)
            assert "-S" not in fence.replace("-Sx", "")

    def test_recipe_never_uses_the_forbidden_literals(self) -> None:
        from carter.identity.rules import render_forbidden_commands

        offenders = [
            (lit, fence.strip().splitlines()[0])
            for fence in _code_fences(_ops_text())
            for lit in render_forbidden_commands()
            if lit in fence
        ]
        assert offenders == []

    def test_recipe_stages_explicit_paths_only(self) -> None:
        fences = "\n".join(_code_fences(_ops_text()))
        assert "git add <file1> <file2>" in fences
        assert not re.search(r"git add (-A|--all|\.)(\s|$)", fences)
        assert not re.search(r"git commit\b[^\n]*\s-[a-z]*a[a-z]*\b", fences)

    def test_recipe_verifies_the_commit_shape(self) -> None:
        text = _ops_text()
        assert "git log -1 --format='%an|%cn|%G?'" in text
        assert "git config user.name" in text
        assert "`N`" in text  # unsigned is the expected status in this release

    def test_trailer_comes_from_the_runtime_emit_not_from_the_file(self) -> None:
        text = _ops_text()
        assert "carter ops config --emit" in text
        for key in ("coauthor_trailer", "tier", "commits", "refusal_reason", "footer"):
            assert f"`{key}`" in text, key
        assert '--trailer "<coauthor_trailer>"' in text
        assert not re.search(r"Co-authored-by: [A-Za-z0-9-]+ <[^<>\s]+@", text)  # no literal

    def test_refused_means_stop_and_report(self) -> None:
        text = _ops_text()
        assert re.search(r"`commits` is `refused`[^.]*stop", text, re.I)
        assert "report" in text.lower() and "`refusal_reason`" in text

    def test_interim_shape_is_stated(self) -> None:
        text = " ".join(_ops_text().split())
        assert "user's own git config" in text
        assert "unsigned" in text
        for flag in ("--author", "--no-verify", "-s", "-S"):
            assert f"`{flag}`" in text

    def test_footer_is_the_emitted_one(self) -> None:
        text = _ops_text()
        assert "{{" not in text
        assert "generated by" not in text.lower().replace("generated from", "")

    def test_rendered_blocks_are_present(self) -> None:
        from carter.identity.blocks import check_text

        assert check_text(_ops_text()) == []

    def test_error_recovery_has_no_signing_retry(self) -> None:
        assert "proceed without signing" not in _ops_text()


# ─── Attribution wording agrees everywhere (plan 002 step 17) ───

WORDING_FILES = [
    "skills/carter-pipeline/SKILL.md",
    "skills/carter-docs/SKILL.md",
    "templates/instructions/AGENTS.md.j2",
    "templates/agents/carter-engineer.md.j2",
    "templates/agents/carter-devops.md.j2",
    "templates/agents/carter-maestro.md.j2",
]
STALE_WORDING = (
    "signed `-S`",
    "sign with your own key",
    "bot identity from `~/.carter/config.toml`",
    "bot identity from",
    "carter-bot",
)


@pytest.mark.parametrize("name", WORDING_FILES)
def test_attribution_wording_points_to_carter_ops_and_the_emit(name: str) -> None:
    text = " ".join((REPO / name).read_text(encoding="utf-8").split())
    assert "carter-ops" in text, name
    assert "coauthor_trailer" in text, name
    assert "`--author`" in text, name
    for stale in STALE_WORDING:
        assert stale not in text, (name, stale)


def test_the_user_is_never_said_to_sign() -> None:
    for name in WORDING_FILES:
        text = (REPO / name).read_text(encoding="utf-8")
        assert not re.search(r"user is (?:the )?(?:commit )?author \(signed", text), name
