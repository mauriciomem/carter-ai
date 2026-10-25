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
    _count_step_rows,
    _validate_plan_dir,
    parse_frontmatter,
    validate_checkpoint,
    validate_plans_dir,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def validate_plan_dir(plan_dir: Path, thresholds: dict | None = None) -> list[str]:
    """Errors for one plan directory, via the path ``validate_plans_dir`` uses."""
    return _validate_plan_dir(plan_dir, thresholds)[0]


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

    @pytest.mark.parametrize(
        "key", ["id", "status", "created", "updated", "push_policy", "must_haves"]
    )
    def test_missing_required_key(self, tmp_path, key):
        readme = VALID_README.replace(f"{key}:", f"x_{key}:", 1)
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any(key in e and "required" in e.lower() for e in errors)

    def test_unreadable_readme_returns_error_not_raises(self, tmp_path):
        """A non-UTF-8/binary README yields a validation error, never a traceback."""
        plan_dir = tmp_path / "active" / "001-binary"
        plan_dir.mkdir(parents=True)
        (plan_dir / "README.md").write_bytes(b"\xff\xfe\x00\x01 not utf-8")
        errors = validate_plan_dir(plan_dir)  # must not raise
        assert errors
        assert any("README" in e for e in errors)

    def test_readme_is_a_directory_returns_error(self, tmp_path):
        """A README.md that is a directory yields an error, never a traceback."""
        plan_dir = tmp_path / "active" / "001-dir"
        (plan_dir / "README.md").mkdir(parents=True)
        errors = validate_plan_dir(plan_dir)  # must not raise
        assert errors
        assert any("README" in e for e in errors)

    def test_unreadable_step_file_returns_error(self, tmp_path):
        plan = make_plan(tmp_path)
        (plan / "step-01.md").write_bytes(b"\xff\xfe\x00 binary")
        errors = validate_plan_dir(plan)  # must not raise
        assert any("step-01.md" in e for e in errors)


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
            'must_haves:\n  truths:\n    - "The sample behaviour works"\n'
            "  artifacts: []\n  key_links: []",
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

    def test_duplicate_numeric_id_flagged(self, tmp_path):
        """001-foo and 001-bar share the NNN prefix within one bucket."""
        make_plan(
            tmp_path,
            name="001-foo",
            state="active",
            readme=VALID_README.replace("id: 001-sample-plan", "id: 001-foo"),
        )
        make_plan(
            tmp_path,
            name="001-bar",
            state="active",
            readme=VALID_README.replace("id: 001-sample-plan", "id: 001-bar"),
        )
        errors = validate_plans_dir(tmp_path)
        assert any("001" in e and "duplicate" in e.lower() for e in errors)

    def test_distinct_numeric_ids_clean(self, tmp_path):
        make_plan(
            tmp_path,
            name="001-foo",
            state="active",
            readme=VALID_README.replace("id: 001-sample-plan", "id: 001-foo"),
        )
        make_plan(
            tmp_path,
            name="002-bar",
            state="active",
            readme=VALID_README.replace("id: 001-sample-plan", "id: 002-bar"),
        )
        assert not any("duplicate" in e.lower() for e in validate_plans_dir(tmp_path))

    def test_duplicate_numeric_id_across_buckets_flagged(self, tmp_path):
        """NNN must be unique globally, not just within a bucket (001 in active/ + completed/)."""
        make_plan(
            tmp_path,
            name="001-foo",
            state="active",
            readme=VALID_README.replace("id: 001-sample-plan", "id: 001-foo"),
        )
        # 001-done is completed-status, correctly in completed/, but shares NNN 001
        done = VALID_README.replace("id: 001-sample-plan", "id: 001-done").replace(
            "status: active", "status: completed"
        )
        make_plan(tmp_path, name="001-done", state="completed", readme=done)
        errors = validate_plans_dir(tmp_path)
        assert any("001" in e and "duplicate" in e.lower() for e in errors)


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
        skill = Path(__file__).resolve().parent.parent / "skills" / "carter-plan" / "SKILL.md"
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
            "---\nupdated: 2026-06-09T18:00:00Z\nactive_plan: 001-x\n"
            "next_step: 4\n---\nwhere we left off\n",
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

    def test_next_step_bool_rejected(self, tmp_path):
        """bool is a subclass of int, but `next_step: true` is not a step index."""
        f = tmp_path / "checkpoint.md"
        f.write_text("---\nupdated: x\nnext_step: true\n---\n", encoding="utf-8")
        assert any("next_step" in e for e in validate_checkpoint(f))

    def test_unreadable_checkpoint_returns_error(self, tmp_path):
        f = tmp_path / "checkpoint.md"
        f.write_bytes(b"\xff\xfe\x00 binary")
        assert any("checkpoint" in e for e in validate_checkpoint(f))  # must not raise


# ─── step-01 #1: checkpoint <-> plan cross-reference ──────────────────────────


class TestCheckpointCrossRef:
    """When given the plans root, the checkpoint's active_plan must resolve to a
    real plan under active/ — a dangling pointer misdirects session recovery."""

    def _checkpoint(self, tmp_path, active_plan: str) -> Path:
        f = tmp_path / "checkpoint.md"
        f.write_text(
            f"---\nupdated: 2026-06-10\nactive_plan: {active_plan}\nnext_step: 1\n---\n",
            encoding="utf-8",
        )
        return f

    def test_dangling_pointer_flagged(self, tmp_path):
        plans_root = tmp_path / "plans"
        (plans_root / "active").mkdir(parents=True)
        cp = self._checkpoint(tmp_path, "001-missing")
        errors = validate_checkpoint(cp, plans_root)
        assert any("001-missing" in e and "active_plan" in e for e in errors)

    def test_traversal_active_plan_flagged(self, tmp_path):
        # a '..'-traversal pointer must be flagged, never accepted by escaping active/
        plans_root = tmp_path / "plans"
        (plans_root / "active").mkdir(parents=True)
        (tmp_path / "elsewhere").mkdir()
        cp = self._checkpoint(tmp_path, "../../elsewhere")
        errors = validate_checkpoint(cp, plans_root)
        assert any("active_plan" in e for e in errors)

    def test_valid_pointer_clean(self, tmp_path):
        plans_root = tmp_path / "plans"
        make_plan(
            plans_root,
            name="001-real",
            state="active",
            readme=VALID_README.replace("id: 001-sample-plan", "id: 001-real"),
        )
        cp = self._checkpoint(tmp_path, "001-real")
        assert validate_checkpoint(cp, plans_root) == []

    def test_null_active_plan_clean(self, tmp_path):
        plans_root = tmp_path / "plans"
        (plans_root / "active").mkdir(parents=True)
        f = tmp_path / "checkpoint.md"
        f.write_text("---\nupdated: 2026-06-10\nactive_plan: null\n---\n", encoding="utf-8")
        assert validate_checkpoint(f, plans_root) == []

    def test_without_plans_root_skips_crossref(self, tmp_path):
        # backward-compatible: no plans_root => no cross-check, still valid
        cp = self._checkpoint(tmp_path, "001-missing")
        assert validate_checkpoint(cp) == []


# ─── step-01 #2: folder <-> status coherence ──────────────────────────────────


class TestFolderStatusCoherence:
    """A terminal-status plan in active/ (or in-progress plan in completed/) is a
    bucket/status mismatch the maestro would misread."""

    def _plan_with_status(self, plans_root, name, state, status):
        readme = VALID_README.replace("id: 001-sample-plan", f"id: {name}").replace(
            "status: active", f"status: {status}"
        )
        return make_plan(plans_root, name=name, state=state, readme=readme)

    def test_completed_status_in_active_flagged(self, tmp_path):
        self._plan_with_status(tmp_path, "001-done", "active", "completed")
        errors = validate_plans_dir(tmp_path)
        assert any("001-done" in e and "active" in e.lower() for e in errors)

    def test_abandoned_status_in_active_flagged(self, tmp_path):
        self._plan_with_status(tmp_path, "001-gone", "active", "abandoned")
        errors = validate_plans_dir(tmp_path)
        assert any("001-gone" in e for e in errors)

    def test_active_status_in_completed_flagged(self, tmp_path):
        self._plan_with_status(tmp_path, "001-wip", "completed", "active")
        errors = validate_plans_dir(tmp_path)
        assert any("001-wip" in e and "completed" in e.lower() for e in errors)

    def test_proposed_in_active_is_clean(self, tmp_path):
        self._plan_with_status(tmp_path, "001-draft", "active", "proposed")
        errors = validate_plans_dir(tmp_path)
        assert not any("001-draft" in e for e in errors)

    def test_blocked_in_active_is_clean(self, tmp_path):
        self._plan_with_status(tmp_path, "001-stuck", "active", "blocked")
        errors = validate_plans_dir(tmp_path)
        assert not any("001-stuck" in e for e in errors)

    def test_completed_in_completed_is_clean(self, tmp_path):
        self._plan_with_status(tmp_path, "001-fin", "completed", "completed")
        errors = validate_plans_dir(tmp_path)
        assert not any("001-fin" in e for e in errors)


# ─── step-02: validator strict mode (#3 #4 #5 #6) ─────────────────────────────


class TestStrictMode:
    # #3 — unknown must_haves sub-key
    def test_unknown_must_haves_key_reported(self, tmp_path):
        readme = VALID_README.replace("  truths:", "  truth:")  # singular typo
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any("must_haves" in e and "unknown" in e.lower() for e in errors)

    def test_known_must_haves_keys_no_unknown_error(self, tmp_path):
        plan = make_plan(tmp_path)  # VALID_README uses the three known keys
        errors = validate_plan_dir(plan)
        assert not any("unknown" in e.lower() for e in errors)

    # #4 — created / updated must be dates
    @pytest.mark.parametrize("key", ["created", "updated"])
    def test_non_date_created_updated_flagged(self, tmp_path, key):
        readme = VALID_README.replace(f"{key}: 2026-06-09", f"{key}: not-a-date")
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any(key in e and "date" in e.lower() for e in errors)

    def test_iso_dates_accepted(self, tmp_path):
        plan = make_plan(tmp_path)  # 2026-06-09 unquoted -> date object
        assert not any("date" in e.lower() for e in validate_plan_dir(plan))

    @pytest.mark.parametrize("bad", ["2026-13-45", "2026-00-10", "2026-02-30"])
    def test_quoted_impossible_dates_rejected(self, tmp_path, bad):
        # quoted -> YAML keeps a string; calendar validation must reject it
        readme = VALID_README.replace("created: 2026-06-09", f'created: "{bad}"')
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)
        assert any("created" in e and "date" in e.lower() for e in errors)

    @pytest.mark.parametrize("bad", ["2026-13-45", "2026-02-30"])
    def test_unquoted_impossible_dates_do_not_crash(self, tmp_path, bad):
        # unquoted -> YAML raises ValueError during construction; must be caught,
        # never propagate as a traceback, and yield a validation error.
        readme = VALID_README.replace("created: 2026-06-09", f"created: {bad}")
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan)  # must not raise
        assert errors

    # #5 — step file: integer step matched to filename; depends_on are ints
    def test_step_value_not_integer(self, tmp_path):
        plan = make_plan(tmp_path)
        (plan / "step-01.md").write_text(
            "---\nstep: two\nstatus: pending\ndepends_on: []\n---\n", encoding="utf-8"
        )
        errors = validate_plan_dir(plan)
        assert any("step-01.md" in e and "integer" in e.lower() for e in errors)

    def test_step_value_mismatches_filename(self, tmp_path):
        plan = make_plan(tmp_path)
        (plan / "step-01.md").write_text(
            "---\nstep: 9\nstatus: pending\ndepends_on: []\n---\n", encoding="utf-8"
        )
        errors = validate_plan_dir(plan)
        assert any("step-01.md" in e and "filename" in e.lower() for e in errors)

    def test_depends_on_non_int_elements(self, tmp_path):
        plan = make_plan(tmp_path)
        (plan / "step-01.md").write_text(
            "---\nstep: 1\nstatus: pending\ndepends_on: [one]\n---\n", encoding="utf-8"
        )
        errors = validate_plan_dir(plan)
        assert any("step-01.md" in e and "depends_on" in e for e in errors)

    def test_step_matched_filename_is_clean(self, tmp_path):
        plan = make_plan(tmp_path)
        (plan / "step-01.md").write_text(
            "---\nstep: 1\nstatus: pending\ndepends_on: [2]\n---\n", encoding="utf-8"
        )
        assert not any("step-01.md" in e for e in validate_plan_dir(plan))

    # #6 — a prose (numbered-list) step list does not silently bypass the split rule
    def test_prose_step_list_over_threshold_flagged(self, tmp_path):
        prose = "\n".join(f"{i}. Step {i}" for i in range(1, 6))
        readme = VALID_README.replace("| 1 | Do it | pending |", prose)
        # drop the table header/separator so only the prose list remains
        readme = readme.replace("| # | Step | Status |\n|---|------|--------|\n", "")
        plan = make_plan(tmp_path, readme=readme)
        errors = validate_plan_dir(plan, {"step_file_threshold": 3})
        assert any("step" in e.lower() for e in errors)


class TestCountStepRowsHeuristic:
    """Document the _count_step_rows heuristic's known shapes and limits."""

    def test_table_counts_data_rows(self):
        text = "## Steps\n| # | Step | Status |\n|---|---|---|\n| 1 | a | x |\n| 2 | b | y |\n"
        assert _count_step_rows(text) == 2

    def test_prose_numbered_list_counts(self):
        text = "## Steps\n1. first\n2. second\n3. third\n"
        assert _count_step_rows(text) == 3

    def test_no_steps_section_returns_none(self):
        assert _count_step_rows("# Plan\n\nNo steps here.\n") is None

    def test_table_preferred_over_prose(self):
        text = "## Steps\n| # | S |\n|---|---|\n| 1 | a |\n\n1. stray line\n"
        # table present -> table count wins (1 data row), prose ignored
        assert _count_step_rows(text) == 1

    def test_only_counts_steps_section(self):
        text = "## Other\n1. not a step\n2. also not\n\n## Steps\n1. real step\n"
        assert _count_step_rows(text) == 1

    def test_ignores_non_steps_step_prefixed_section(self):
        # '## Step-by-step' is prose, not the Steps table — must not be counted
        text = "## Step-by-step guide\n1. do a\n2. do b\n3. do c\n4. do d\n"
        assert _count_step_rows(text) is None
