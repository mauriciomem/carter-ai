"""Implementer-adherence eval (P4-eval — RFC-0005 §2 D2.5 / ADR-0010 D9).

The reliability backstop for the cheap-tier (Sonnet 4.6) implementer default. It runs
the implementer against a thinker-produced plan with real `must_haves` (named file
paths, acceptance checks, step-level instructions) and grades adherence: the fraction
of must_haves satisfied + whether any CRITICAL step was missed.

Pass-bar (D9): >= 90% of must_haves satisfied AND 0 critical-step failures.

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
    """The thinker-produced plan must carry the executable shape D9 fixes at the Opus bar."""

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
        # D9: the doc-quality contract is part of the eval (docs stay at the Opus bar).
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
    the empirical evidence the cheap-tier default is shippable (D9). This is the
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
