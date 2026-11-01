"""Offline skill correctness eval — validates skill files contain the right patterns.

These tests verify:
1. Skills contain expected command templates and patterns
2. Carter-ops skill reads attribution from `carter ops config --emit` at runtime
3. Skills don't teach anti-patterns
4. Workflow phases are documented in correct order
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture
def ops_skill(skills_dir: Path) -> str:
    return (skills_dir / "carter-ops" / "SKILL.md").read_text()


class TestCarterOpsSkillContent:
    """Verify carter-ops SKILL.md teaches the correct patterns."""

    def test_workflow_phases_present(self, ops_skill: str) -> None:
        """All 6 workflow phases must be documented."""
        phases = ["ASSESS", "PLAN", "APPROVE", "EXECUTE", "AUDIT", "REPORT"]
        for phase in phases:
            assert phase in ops_skill, f"Missing workflow phase: {phase}"

    def test_workflow_phases_ordered(self, ops_skill: str) -> None:
        """Phases must appear in correct order."""
        phases = ["ASSESS", "PLAN", "APPROVE", "EXECUTE", "AUDIT", "REPORT"]
        positions = [ops_skill.index(p) for p in phases]
        assert positions == sorted(positions), "Workflow phases are out of order"

    def test_has_attribution_from_the_runtime_emit(self, ops_skill: str) -> None:
        """The trailer comes from `carter ops config --emit`, never from the file."""
        assert '--trailer "<coauthor_trailer>"' in ops_skill
        assert "carter ops config --emit" in ops_skill
        assert "{{" not in ops_skill
        # The bot never overrides the author: no `git commit --author=...` form.
        assert "--author=" not in ops_skill and "--author '" not in ops_skill

    def test_recipe_never_signs_and_verifies_the_commit(self, ops_skill: str) -> None:
        """No `git commit -S`; the recipe checks author, committer and signature status."""
        assert "git commit -S" not in ops_skill
        assert "git log -1 --format='%an|%cn|%G?'" in ops_skill

    def test_recipe_stages_explicit_paths(self, ops_skill: str) -> None:
        assert "git add <file1> <file2>" in ops_skill
        for forbidden in ("git add -A", "git add .", "git commit -a"):
            for fence in re.findall(r"```bash\n(.*?)```", ops_skill, flags=re.S):
                assert forbidden not in fence

    def test_refusal_is_fail_closed_in_words(self, ops_skill: str) -> None:
        assert re.search(r"`commits` is `refused`[^.]*stop", ops_skill, re.I)
        assert "`refusal_reason`" in ops_skill

    def test_has_runtime_identity_keys(self, ops_skill: str) -> None:
        """Identity is read at runtime: the skill names the emitted keys."""
        for key in ("tier", "role", "role_source", "coauthor_trailer", "commits", "refusal_reason"):
            assert f"`{key}`" in ops_skill, key

    def test_approval_gate_enforced(self, ops_skill: str) -> None:
        """Must explicitly require user approval before execution."""
        approval_patterns = [
            "wait for",
            "user confirmation",
            "approval",
            "NEVER execute write commands without",
        ]
        found = any(p.lower() in ops_skill.lower() for p in approval_patterns)
        assert found, "No approval gate enforcement found in skill"

    def test_teaches_direct_execution(self, ops_skill: str) -> None:
        """Must teach running commands directly, not through CLI wrapper."""
        # Should have actual git command templates
        assert "git commit" in ops_skill
        assert "git push" in ops_skill
        assert "git checkout" in ops_skill
        # Should NOT teach CLI invocation as primary path
        assert "--execute" not in ops_skill
        assert "--dry-run" not in ops_skill

    def test_has_audit_command(self, ops_skill: str) -> None:
        """Must include the audit command template."""
        assert "carter ops audit" in ops_skill
        assert "--operation" in ops_skill
        assert "--result" in ops_skill

    def test_has_github_operations(self, ops_skill: str) -> None:
        """Must cover gh CLI commands."""
        assert "gh issue" in ops_skill
        assert "gh pr" in ops_skill

    def test_has_footer_for_github(self, ops_skill: str) -> None:
        """Must teach appending the emitted footer to GitHub body fields."""
        assert "footer" in ops_skill.lower()
        assert "`footer` from `carter ops config --emit`" in ops_skill

    def test_has_jira_operations(self, ops_skill: str) -> None:
        """Jira goes through the carter-atlassian MCP server, never curl/REST."""
        assert "jira" in ops_skill.lower()
        assert "carter-atlassian" in ops_skill
        assert "rest/api/" not in ops_skill

    def test_no_legacy_cli_invocations(self, ops_skill: str) -> None:
        """Skill should not teach the legacy CLI as primary execution method."""
        # These are legacy patterns that should not be the taught approach
        # The `carter-ops` binary no longer exists; the CLI is `carter ops`, and it
        # has no git/gh/jira operations — the model runs those commands directly.
        for legacy in ("carter-ops git-", "carter-ops gh-", "carter-ops jira-", "carter-ops audit"):
            assert legacy not in ops_skill
        for op in ("git-", "gh-", "jira-"):
            assert f"carter ops {op}" not in ops_skill


class TestSkillStructure:
    """Verify all skills follow the expected structure."""

    def test_all_skills_have_frontmatter(self, skills_dir: Path) -> None:
        """Every SKILL.md must have YAML frontmatter with name and description."""
        missing_frontmatter = []
        for skill_dir in sorted(skills_dir.glob("carter-*")):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            content = skill_md.read_text()
            if not content.startswith("---"):
                missing_frontmatter.append(skill_dir.name)
                continue
            # Check for name and description in frontmatter
            fm_end = content.index("---", 3)
            frontmatter = content[3:fm_end]
            if "name:" not in frontmatter:
                missing_frontmatter.append(f"{skill_dir.name} (missing name)")
            if "description:" not in frontmatter:
                missing_frontmatter.append(f"{skill_dir.name} (missing description)")
        assert not missing_frontmatter, f"Skills with bad frontmatter: {missing_frontmatter}"

    def test_all_skills_have_content(self, skills_dir: Path) -> None:
        """Every SKILL.md must have substantive content beyond frontmatter."""
        thin_skills = []
        for skill_dir in sorted(skills_dir.glob("carter-*")):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            content = skill_md.read_text()
            # Strip frontmatter
            if content.startswith("---"):
                fm_end = content.index("---", 3) + 3
                body = content[fm_end:]
            else:
                body = content
            if len(body.strip()) < 100:
                thin_skills.append(skill_dir.name)
        assert not thin_skills, f"Skills with insufficient content: {thin_skills}"


class TestSkillPatternCoverage:
    """Verify skills teach expected patterns (offline check against skill content)."""

    def test_terraform_skill_covers_basics(self, skills_dir: Path) -> None:
        skill = (skills_dir / "carter-terraform" / "SKILL.md").read_text()
        assert "variable" in skill
        assert "resource" in skill
        assert "output" in skill
        assert "module" in skill

    def test_python_skill_covers_basics(self, skills_dir: Path) -> None:
        skill = (skills_dir / "carter-python" / "SKILL.md").read_text()
        assert "pyproject.toml" in skill or "project structure" in skill.lower()
        assert "type" in skill  # type annotations/hints
        assert "pytest" in skill or "test" in skill

    def test_golang_skill_covers_basics(self, skills_dir: Path) -> None:
        skill = (skills_dir / "carter-golang" / "SKILL.md").read_text()
        assert "error" in skill
        assert "func" in skill
        assert "test" in skill.lower()

    def test_golang_skill_covers_networking(self, skills_dir: Path) -> None:
        # Networking is the deepest focus area; content lives in sibling files.
        content = "".join(f.read_text() for f in (skills_dir / "carter-golang").glob("**/*.md"))
        assert "ReadHeaderTimeout" in content  # full server timeout set
        assert "Shutdown" in content  # graceful shutdown
        assert "context" in content  # request context propagation
        assert "Transport" in content  # client connection pooling

    def test_golang_skill_covers_focus_areas(self, skills_dir: Path) -> None:
        # Concurrency, APIs, QA, and performance each have substantive coverage.
        content = "".join(f.read_text() for f in (skills_dir / "carter-golang").glob("**/*.md"))
        assert "errgroup" in content  # concurrency
        assert "goroutine" in content  # concurrency / leak prevention
        assert "MaxBytesReader" in content  # API JSON safety
        assert "DisallowUnknownFields" in content  # API JSON safety
        assert "goleak" in content  # test-first QA
        assert "fuzz" in content.lower()  # fuzzing
        assert "pprof" in content  # performance profiling
        assert "benchstat" in content  # benchmark comparison

    def test_pipeline_skill_covers_github_actions(self, skills_dir: Path) -> None:
        # Pipeline skill may have sub-files
        skill_dir = skills_dir / "carter-pipeline"
        all_content = ""
        for f in skill_dir.glob("**/*.md"):
            all_content += f.read_text()
        assert "GitHub Actions" in all_content or "github actions" in all_content.lower()
        assert "workflow" in all_content.lower()
        assert "on:" in all_content or "trigger" in all_content.lower()

    def test_code_review_skill_covers_security(self, skills_dir: Path) -> None:
        skill = (skills_dir / "carter-code-review" / "SKILL.md").read_text()
        assert "security" in skill.lower()

    def test_packer_skill_covers_hcl2(self, skills_dir: Path) -> None:
        skill_dir = skills_dir / "carter-packer"
        all_content = ""
        for f in skill_dir.glob("**/*.md"):
            all_content += f.read_text()
        assert "source" in all_content
        assert "build" in all_content
        assert "HCL" in all_content or "hcl" in all_content
