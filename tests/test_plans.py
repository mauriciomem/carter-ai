"""Tests for carter.plans — the ADR-0003 plan frontmatter validator.

The validator enforces the contract in docs/reference/frontmatter.md (D6):
required keys, status/push_policy enums, id↔directory match, must_haves shape,
the O6 rule (an ``active`` plan must declare >= 1 must_haves entry), and the
configurable size/step thresholds.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from carter.plans import (
    parse_frontmatter,
    validate_checkpoint,
    validate_plan_dir,
    validate_plans_dir,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


VALID_README = textwrap.dedent(
    """\
    ---
    id: 001-sample-plan
    status: active
    created: 2026-06-09
    updated: 2026-06-09
    adr: null
    push_policy: manual
    tags: []
    repos: []
    must_haves:
      truths:
        - "The sample behaviour works"
      artifacts: []
      key_links: []
    ---

    # Plan: Sample

    ## Objective
    Do the thing.

    ## Steps
    | # | Step | Status |
    |---|------|--------|
    | 1 | Do it | pending |
    """
)


def make_plan(
    plans_root: Path,
    name: str = "001-sample-plan",
    state: str = "active",
    readme: str = VALID_README,
) -> Path:
    """Write a plan directory under ``plans_root/<state>/<name>/`` and return it."""
    plan_dir = plans_root / state / name
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "README.md").write_text(readme, encoding="utf-8")
    return plan_dir


# ─── parse_frontmatter ───────────────────────────────────────────────────────


class TestParseFrontmatter:
    def test_valid_block(self):
        fm = parse_frontmatter(VALID_README)
        assert fm is not None
        assert fm["id"] == "001-sample-plan"
        assert fm["status"] == "active"
        assert fm["must_haves"]["truths"] == ["The sample behaviour works"]

    def test_no_frontmatter_returns_none(self):
        assert parse_frontmatter("# Just a heading\n\nbody") is None

    def test_missing_closing_delimiter_returns_none(self):
        assert parse_frontmatter("---\nid: x\nstatus: active\n") is None

    def test_malformed_yaml_returns_none(self):
        assert parse_frontmatter("---\nid: : : :\n bad\n---\n") is None

    def test_non_mapping_returns_none(self):
        assert parse_frontmatter("---\n- just\n- a\n- list\n---\n") is None

    def test_tolerates_leading_bom(self):
        fm = parse_frontmatter("\ufeff" + VALID_README)
        assert fm is not None
        assert fm["id"] == "001-sample-plan"


# ─── validate_plan_dir — happy path ──────────────────────────────────────────


class TestValidPlan:
    def test_valid_active_plan_has_no_errors(self, tmp_path):
        plan = make_plan(tmp_path)
        assert validate_plan_dir(plan) == []


# ─── validate_plan_dir — structural errors ───────────────────────────────────


class TestStructuralErrors:
    def test_missing_readme(self, tmp_path):
        plan_dir = tmp_path / "active" / "001-empty"
        plan_dir.mkdir(parents=True)
        errors = validate_plan_dir(plan_dir)
        assert any("README" in e for e in errors)

    def test_missing_frontmatter(self, tmp_path):
        plan = make_plan(tmp_path, readme="# No frontmatter here\n")
        errors = validate_plan_dir(plan)
        assert any("frontmatter" in e for e in errors)

    @pytest.mark.parametrize("key", ["id", "status", "created", "updated", "push_policy", "must_haves"])
    def test_missing_required_key(self, tmp_path, key):
        readme = VALID_README.replace(f"{key}:", f"x_{key}:", 1)
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any(key in e and "required" in e.lower() for e in errors)


# ─── validate_plan_dir — id rules ────────────────────────────────────────────


class TestIdRules:
    def test_bad_id_format(self, tmp_path):
        readme = VALID_README.replace("id: 001-sample-plan", "id: Sample_Plan")
        plan = make_plan(tmp_path, name="Sample_Plan", readme=readme)
        errors = validate_plan_dir(plan)
        assert any("NNN-kebab" in e or "id" in e for e in errors)

    def test_id_must_match_directory_name(self, tmp_path):
        # id says 001-sample-plan but the directory is 002-other
        plan = make_plan(tmp_path, name="002-other")
        errors = validate_plan_dir(plan)
        assert any("match" in e.lower() and "director" in e.lower() for e in errors)


# ─── validate_plan_dir — enums ───────────────────────────────────────────────


class TestEnums:
    def test_bad_status(self, tmp_path):
        readme = VALID_README.replace("status: active", "status: wip")
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any("status" in e for e in errors)

    def test_bad_push_policy(self, tmp_path):
        readme = VALID_README.replace("push_policy: manual", "push_policy: yolo")
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any("push_policy" in e for e in errors)


# ─── validate_plan_dir — must_haves + O6 ─────────────────────────────────────


class TestMustHaves:
    def test_must_haves_not_a_mapping(self, tmp_path):
        readme = VALID_README.replace(
            'must_haves:\n  truths:\n    - "The sample behaviour works"\n  artifacts: []\n  key_links: []',
            "must_haves: nope",
        )
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any("must_haves" in e for e in errors)

    def test_active_plan_with_empty_must_haves_fails_o6(self, tmp_path):
        readme = VALID_README.replace('    - "The sample behaviour works"\n', "")
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any("active" in e.lower() and "must_haves" in e for e in errors)

    def test_proposed_plan_with_empty_must_haves_is_allowed(self, tmp_path):
        readme = VALID_README.replace("status: active", "status: proposed").replace(
            '    - "The sample behaviour works"\n', ""
        )
        plan = make_plan(tmp_path, readme=readme)
        # O6 only gates "active"; a proposed plan may still be filling in must_haves
        assert validate_plan_dir(plan) == []


# ─── validate_plan_dir — size + step thresholds ──────────────────────────────


class TestThresholds:
    def test_readme_over_budget(self, tmp_path):
        bloat = "\n".join(f"line {i}" for i in range(200))
        plan = make_plan(tmp_path, readme=VALID_README + bloat)
        errors = validate_plan_dir(plan, {"readme_max_lines": 150})
        assert any("exceeds" in e and "README" in e for e in errors)

    def test_steps_over_threshold_require_step_files(self, tmp_path):
        rows = "\n".join(f"| {i} | Step {i} | pending |" for i in range(1, 6))
        readme = VALID_README.replace("| 1 | Do it | pending |", rows)
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan, {"step_file_threshold": 3})
        assert any("step" in e.lower() for e in errors)

    def test_step_file_over_budget(self, tmp_path):
        plan = make_plan(tmp_path)
        step = plan / "step-01.md"
        step.write_text(
            "---\nstep: 1\nstatus: pending\ndepends_on: []\n---\n"
            + "\n".join(f"line {i}" for i in range(100)),
            encoding="utf-8",
        )
        errors = validate_plan_dir(plan, {"step_max_lines": 80})
        assert any("step-01.md" in e and "exceeds" in e for e in errors)

    def test_step_file_bad_status(self, tmp_path):
        plan = make_plan(tmp_path)
        step = plan / "step-01.md"
        step.write_text("---\nstep: 1\nstatus: wip\ndepends_on: []\n---\n", encoding="utf-8")
        errors = validate_plan_dir(plan)
        assert any("step-01.md" in e and "status" in e for e in errors)


# ─── validate_plans_dir — directory scan ─────────────────────────────────────


class TestValidatePlansDir:
    def test_scans_active_and_completed(self, tmp_path):
        # 'good' plan: id matches its directory name, so it validates clean
        make_plan(tmp_path, name="001-sample-plan", state="active")
        make_plan(
            tmp_path,
            name="002-bad",
            state="completed",
            readme=VALID_README.replace("id: 001-sample-plan", "id: 002-bad").replace(
                "status: active", "status: nonsense"
            ),
        )
        errors = validate_plans_dir(tmp_path)
        assert any("002-bad" in e for e in errors)
        assert not any("001-sample-plan" in e for e in errors)

    def test_empty_plans_dir_is_clean(self, tmp_path):
        (tmp_path / "active").mkdir()
        (tmp_path / "completed").mkdir()
        assert validate_plans_dir(tmp_path) == []

    def test_missing_plans_dir_is_clean(self, tmp_path):
        assert validate_plans_dir(tmp_path / "does-not-exist") == []


# ─── carter check CLI integration ────────────────────────────────────────────


class TestCheckIntegration:
    """`carter check` runs the plan validator over an initialized workspace."""

    def _init(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--no-git-state"])
        assert result.exit_code == 0, result.output
        return runner, main

    def test_check_passes_with_a_valid_plan(self, tmp_path):
        runner, main = self._init(tmp_path)
        make_plan(tmp_path / ".carter" / "state" / "plans")
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Workspace OK" in result.output

    def test_check_fails_on_invalid_plan(self, tmp_path):
        runner, main = self._init(tmp_path)
        # active plan with empty must_haves violates O6
        bad = VALID_README.replace('    - "The sample behaviour works"\n', "")
        make_plan(tmp_path / ".carter" / "state" / "plans", readme=bad)
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 1
        assert "must_haves" in result.output

    def test_check_fails_on_bad_checkpoint(self, tmp_path):
        runner, main = self._init(tmp_path)
        cp = tmp_path / ".carter" / "state" / "sessions" / "checkpoint.md"
        cp.write_text("---\nactive_plan: null\n---\n", encoding="utf-8")  # missing 'updated'
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 1
        assert "checkpoint" in result.output


# ─── skill <-> validator anti-drift contract ─────────────────────────────────


class TestSkillExampleValidates:
    """The carter-plan skill's documented README example must pass the validator.

    This locks the skill and the validator together: if either drifts (the skill
    documents a schema the validator rejects, or vice versa), this test fails.
    """

    def _skill_readme_example(self) -> str:
        skill = (
            Path(__file__).resolve().parent.parent
            / "skills"
            / "carter-plan"
            / "SKILL.md"
        )
        text = skill.read_text(encoding="utf-8")
        # first ```markdown ... ``` fence is the plan README example
        marker = "```markdown"
        start = text.index(marker) + len(marker)
        end = text.index("```", start)
        return text[start:end].lstrip("\n")

    def test_skill_readme_example_passes_validator(self, tmp_path):
        example = self._skill_readme_example()
        # the example's id is 001-feature-name; the directory must match
        plan = make_plan(tmp_path, name="001-feature-name", readme=example)
        assert validate_plan_dir(plan) == []


# ─── validate_checkpoint ───────────────────────────────────────────────


class TestValidateCheckpoint:
    """checkpoint.md is optional; absence is clean, but a present file must be valid."""

    def test_absent_is_clean(self, tmp_path):
        assert validate_checkpoint(tmp_path / "checkpoint.md") == []

    def test_valid(self, tmp_path):
        f = tmp_path / "checkpoint.md"
        f.write_text(
            "---\nupdated: 2026-06-09T18:00:00Z\nactive_plan: 001-x\nnext_step: 4\n---\nwhere we left off\n",
            encoding="utf-8",
        )
        assert validate_checkpoint(f) == []

    def test_valid_with_nulls(self, tmp_path):
        f = tmp_path / "checkpoint.md"
        f.write_text(
            "---\nupdated: 2026-06-09\nactive_plan: null\nnext_step: null\n---\n",
            encoding="utf-8",
        )
        assert validate_checkpoint(f) == []

    def test_missing_frontmatter(self, tmp_path):
        f = tmp_path / "checkpoint.md"
        f.write_text("no frontmatter here\n", encoding="utf-8")
        assert any("frontmatter" in e for e in validate_checkpoint(f))

    def test_missing_updated(self, tmp_path):
        f = tmp_path / "checkpoint.md"
        f.write_text("---\nactive_plan: null\n---\n", encoding="utf-8")
        assert any("updated" in e for e in validate_checkpoint(f))

    def test_bad_active_plan_type(self, tmp_path):
        f = tmp_path / "checkpoint.md"
        f.write_text("---\nupdated: x\nactive_plan: 123\n---\n", encoding="utf-8")
        assert any("active_plan" in e for e in validate_checkpoint(f))

    def test_bad_next_step_type(self, tmp_path):
        f = tmp_path / "checkpoint.md"
        f.write_text("---\nupdated: x\nnext_step: four\n---\n", encoding="utf-8")
        assert any("next_step" in e for e in validate_checkpoint(f))


