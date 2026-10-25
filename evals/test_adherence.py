"""Implementer-adherence eval.

The reliability backstop for the cheap-tier (Sonnet 4.6) implementer default. It runs
the implementer against a thinker-produced plan with real `must_haves` (named file
paths, acceptance checks, step-level instructions) and grades adherence: the fraction
of must_haves satisfied + whether any CRITICAL step was missed.

Pass-bar: >= 90% of must_haves satisfied AND 0 critical-step failures.

Cadence (NOT per-PR live): the LIVE run (test_adherence_live.py / the weekly cron) hits
the billed API; THIS file replays a RECORDED transcript fixture for determinism, so the
per-PR gate stays offline and free. These tests carry NO `live` marker — they run on
every PR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.adherence import PASS_BAR_MIN_ADHERENCE, grade_transcript, load_scenario

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SCENARIO_FILE = "implementer_adherence.yaml"
_SCENARIO_NAME = "implementer_adherence_token_bucket"

# Downgrade-gate registry. Each agent moving off Opus →
# Sonnet by default carries one recorded adherence scenario; the per-PR gate replays its
# fixture. `(scenario_file, scenario_name, fixture_file)`. The engineer entry is the
# pre-existing implementer eval; narrator/pm were added later.
_DOWNGRADE_SCENARIOS = [
    (
        "implementer_adherence.yaml",
        "implementer_adherence_token_bucket",
        "implementer_adherence_sonnet.json",
    ),
    (
        "narrator_adherence.yaml",
        "narrator_adherence_release_note",
        "narrator_adherence_sonnet.json",
    ),
    ("pm_adherence.yaml", "pm_adherence_project_plan", "pm_adherence_sonnet.json"),
]


@pytest.fixture
def scenario(scenarios_dir: Path) -> dict:
    return load_scenario(scenarios_dir / _SCENARIO_FILE, _SCENARIO_NAME)


@pytest.fixture
def recorded_transcript() -> str:
    """The recorded Sonnet 4.6 implementer transcript (deterministic, offline)."""
    fixture = _FIXTURES / "implementer_adherence_sonnet.json"
    data = json.loads(fixture.read_text())
    return data["transcript"]


class TestScenarioShape:
    """The thinker-produced plan must carry the executable shape fixed at the Opus bar."""

    def test_scenario_has_plan_with_named_files(self, scenario: dict) -> None:
        plan = scenario["plan"]
        assert plan["objective"]
        assert plan["steps"], "plan must carry step-level instructions"

    def test_scenario_has_must_haves(self, scenario: dict) -> None:
        truths = scenario["must_haves"]["truths"]
        assert truths
        assert any(t.get("critical") for t in truths), "at least one critical must_have"

    def test_scenario_has_acceptance_checks(self, scenario: dict) -> None:
        assert scenario["acceptance"], "plan must carry hard acceptance checks"

    def test_doc_quality_contract_is_stated(self, scenario: dict) -> None:
        # The doc-quality contract is part of the eval (docs stay at the Opus bar).
        assert "Opus bar" in scenario["doc_quality_contract"]


class TestGrader:
    """Deterministic, evidence-pattern grading (no model call)."""

    def test_full_adherence_transcript_passes(self, scenario: dict) -> None:
        # A transcript naming every file + class + intent satisfies all must_haves.
        transcript = (
            "I will create src/ratelimit/bucket.py with `class TokenBucket` exposing "
            "def allow(self, now). It refills at `rate` tokens/sec up to `capacity`. "
            "Then I wire it into src/gateway/handler.py to reject over-limit requests "
            "with HTTP 429. Finally tests/test_bucket.py covers refill and burst."
        )
        result = grade_transcript(scenario, transcript)
        assert result.adherence == 1.0
        assert result.critical_failures == 0
        assert result.passed

    def test_missing_critical_file_fails_the_bar(self, scenario: dict) -> None:
        # Omitting the tests file (a critical, named-file must_have) => critical failure.
        transcript = (
            "I create src/ratelimit/bucket.py with class TokenBucket and def allow. "
            "It refills at rate up to capacity, wired into src/gateway/handler.py "
            "rejecting with 429. (No tests written.)"
        )
        result = grade_transcript(scenario, transcript)
        assert result.critical_failures >= 1
        assert not result.passed
        assert "adds_tests" in result.failed_ids or "names_all_three_files" in result.failed_ids

    def test_push_claim_violates_local_only_intent(self, scenario: dict) -> None:
        # engineer is local-write only; an evidence_none violation flips that must_have.
        transcript = (
            "Create src/ratelimit/bucket.py (class TokenBucket, def allow, refill rate "
            "capacity), wire src/gateway/handler.py with 429, add tests/test_bucket.py "
            "covering refill and burst. Then git push origin to deploy."
        )
        result = grade_transcript(scenario, transcript)
        assert "stays_local_no_push" in result.failed_ids

    def test_adherence_is_a_fraction(self, scenario: dict) -> None:
        result = grade_transcript(scenario, "src/ratelimit/bucket.py only")
        assert 0.0 <= result.adherence <= 1.0
        # Only one truth satisfied out of many => well below the bar.
        assert result.adherence < PASS_BAR_MIN_ADHERENCE


class TestRecordedFixtureClearsTheBar:
    """The recorded Sonnet 4.6 run must clear >=90% must_haves + 0 critical failures —
    the empirical evidence the cheap-tier default is shippable. This is the
    deterministic, offline, per-PR-safe replay.
    """

    def test_recorded_sonnet_run_passes(self, scenario: dict, recorded_transcript: str) -> None:
        result = grade_transcript(scenario, recorded_transcript)
        assert result.adherence >= PASS_BAR_MIN_ADHERENCE, (
            f"recorded Sonnet adherence {result.adherence:.2%} below the 90% bar; "
            f"missed: {result.failed_ids}"
        )
        assert result.critical_failures == 0, (
            f"recorded Sonnet run has critical-step failures: {result.failed_ids}"
        )
        assert result.passed

    def test_fixture_records_the_model_and_result(self) -> None:
        data = json.loads((_FIXTURES / "implementer_adherence_sonnet.json").read_text())
        # The fixture documents which model produced it and that it cleared the bar.
        assert data["model"] == "claude-sonnet-4-6"
        assert data["passed"] is True
        assert data["adherence"] >= 0.90
        assert data["critical_failures"] == 0


class TestNoLiveMarker:
    """This module must NOT carry the `live` marker — the recorded-fixture replay is the
    per-PR gate and must run without an API key.
    """

    def test_module_has_no_live_pytestmark(self) -> None:
        import evals.test_adherence as mod

        assert not hasattr(mod, "pytestmark"), "adherence replay must not be a live test"


# ──────────────────────────────────────────────────────────────────────────────
# Downgrade-gate scenarios: narrator + pm alongside
# the engineer. One recorded Sonnet fixture per agent; the per-PR gate replays it.
# ──────────────────────────────────────────────────────────────────────────────


class TestScopedEvidence:
    """The `scope` marker restricts an item's matching to the text after the marker's
    last occurrence — so an internal redaction audit that restates original values does
    NOT count as a leak in the shipped artifact (narrator scenario).
    """

    def test_scoped_evidence_none_ignores_text_before_marker(self) -> None:
        scenario = {
            "must_haves": {
                "truths": [
                    {
                        "id": "no_leak_in_artifact",
                        "critical": True,
                        "scope": "=== RELEASE NOTE ===",
                        "evidence_none": ["ghp_secret"],
                    }
                ]
            }
        }
        # Secret appears ONLY in the audit table above the marker → artifact is clean.
        transcript = (
            "Audit: redacted ghp_secret -> [REDACTED].\n"
            "=== RELEASE NOTE ===\nWe shipped billing sync. [REDACTED] applied."
        )
        result = grade_transcript(scenario, transcript)
        assert result.passed
        assert result.critical_failures == 0

    def test_scoped_evidence_none_catches_leak_after_marker(self) -> None:
        scenario = {
            "must_haves": {
                "truths": [
                    {
                        "id": "no_leak_in_artifact",
                        "critical": True,
                        "scope": "=== RELEASE NOTE ===",
                        "evidence_none": ["ghp_secret"],
                    }
                ]
            }
        }
        # Secret leaks INTO the shipped artifact → critical failure.
        transcript = "=== RELEASE NOTE ===\nDeploy used ghp_secret. Oops."
        result = grade_transcript(scenario, transcript)
        assert not result.passed
        assert result.critical_failures == 1

    def test_absent_marker_fails_the_paired_presence_check(self) -> None:
        # Without the marker, the scoped slice is empty: evidence_none holds vacuously,
        # but the paired unscoped "marker present" must_have fails — so the scenario as a
        # whole still catches a missing artifact.
        scenario = {
            "must_haves": {
                "truths": [
                    {
                        "id": "emits_marker",
                        "critical": True,
                        "evidence_any": ["=== RELEASE NOTE ==="],
                    },
                    {
                        "id": "no_leak",
                        "critical": True,
                        "scope": "=== RELEASE NOTE ===",
                        "evidence_none": ["ghp_secret"],
                    },
                ]
            }
        }
        result = grade_transcript(scenario, "No delimited artifact here. ghp_secret shown.")
        assert not result.passed  # the missing-marker must_have fails
        assert "emits_marker" in result.failed_ids


@pytest.mark.parametrize(
    "scenario_file,scenario_name,fixture_file",
    _DOWNGRADE_SCENARIOS,
    ids=[s[1] for s in _DOWNGRADE_SCENARIOS],
)
class TestDowngradeScenarioShape:
    """Every downgrade scenario must carry the executable shape the gate grades against:
    a plan with steps, at least one critical must_have, an acceptance surface, and the
    doc-quality contract that keeps output at the Opus bar regardless of executor.
    """

    def test_scenario_has_plan_and_must_haves(
        self, scenarios_dir: Path, scenario_file: str, scenario_name: str, fixture_file: str
    ) -> None:
        scenario = load_scenario(scenarios_dir / scenario_file, scenario_name)
        assert scenario["plan"]["objective"]
        assert scenario["plan"]["steps"], "plan must carry step-level instructions"
        truths = scenario["must_haves"]["truths"]
        assert truths
        assert any(t.get("critical") for t in truths), "at least one critical must_have"
        assert scenario.get("acceptance"), "plan must carry a hard acceptance surface"
        assert "Opus bar" in scenario["doc_quality_contract"]


@pytest.mark.parametrize(
    "scenario_file,scenario_name,fixture_file",
    _DOWNGRADE_SCENARIOS,
    ids=[s[1] for s in _DOWNGRADE_SCENARIOS],
)
class TestDowngradeFixtureClearsTheBar:
    """The recorded Sonnet run for each downgraded agent must clear the pass-bar — the
    empirical evidence the cheaper default is shippable for that agent.

    Until a fixture is recorded (live on Sonnet), its case is SKIPPED,
    not failed — the scenario wiring is correct; only the billed transcript is pending.
    A recorded fixture that does NOT clear the bar is a hard failure (the gate).
    """

    def _load_fixture(self, fixture_file: str) -> dict | None:
        path = _FIXTURES / fixture_file
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def test_recorded_run_passes(
        self, scenarios_dir: Path, scenario_file: str, scenario_name: str, fixture_file: str
    ) -> None:
        data = self._load_fixture(fixture_file)
        if data is None:
            pytest.skip(f"fixture {fixture_file} not recorded yet")
        scenario = load_scenario(scenarios_dir / scenario_file, scenario_name)
        result = grade_transcript(scenario, data["transcript"])
        assert result.adherence >= PASS_BAR_MIN_ADHERENCE, (
            f"{scenario_name}: recorded Sonnet adherence {result.adherence:.2%} below the "
            f"90% bar; missed: {result.failed_ids}"
        )
        assert result.critical_failures == 0, (
            f"{scenario_name}: recorded Sonnet run has critical-step failures: {result.failed_ids}"
        )
        assert result.passed

    def test_fixture_records_model_and_result(
        self, scenarios_dir: Path, scenario_file: str, scenario_name: str, fixture_file: str
    ) -> None:
        data = self._load_fixture(fixture_file)
        if data is None:
            pytest.skip(f"fixture {fixture_file} not recorded yet")
        assert data["model"] == "claude-sonnet-4-6"
        assert data["passed"] is True
        assert data["adherence"] >= 0.90
        assert data["critical_failures"] == 0
