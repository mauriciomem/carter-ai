"""LIVE implementer-adherence eval (P4-eval — RFC-0005 §2 D2.5 / ADR-0010 D9).

Sends the thinker-produced plan to the **Sonnet 4.6** implementer tier (the
carter-engineer agent prompt) against the live API and grades the real transcript with
the same deterministic grader the offline replay uses. This is the BILLED run.

Cadence: NOT per-PR. It carries the `live` marker (via the shared `test_live` auth
helpers), so the PR gate — which runs `-m "not live"` — never invokes it. It runs on the
weekly `evals-live` cron / `workflow_dispatch`, exactly like the other live evals.

Re-recording the fixture: run this with ``EVAL_RECORD=1`` to overwrite
``evals/fixtures/implementer_adherence_sonnet.json`` with the fresh live transcript +
grade, so the offline replay tracks the current Sonnet behavior.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evals.adherence import PASS_BAR_MIN_ADHERENCE, grade_transcript, load_scenario

# Reuse the live-auth + model-call machinery (and inherit the `live` marker).
from evals.test_live import _call_model

pytestmark = pytest.mark.live

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SCENARIO_FILE = "implementer_adherence.yaml"
_SCENARIO_NAME = "implementer_adherence_token_bucket"


def _plan_prompt(scenario: dict) -> str:
    """Render the thinker plan as the user message handed to the implementer."""
    plan = scenario["plan"]
    steps = "\n".join(f"- {s}" for s in plan["steps"])
    must = "\n".join(f"- {t['id']}" for t in scenario["must_haves"]["truths"])
    return (
        f"Execute this plan. Show the files you create and the code, with explicit "
        f"file paths. Do not use any tools — write the implementation directly.\n\n"
        f"# Plan: {plan['title']}\n\n"
        f"Objective: {plan['objective']}\n\n"
        f"## Steps\n{steps}\n\n"
        f"## Required outcomes (must_haves)\n{must}\n"
    )


class TestLiveImplementerAdherence:
    def test_sonnet_implementer_clears_the_bar(self, agents_dir: Path, scenarios_dir: Path) -> None:
        scenario = load_scenario(scenarios_dir / _SCENARIO_FILE, _SCENARIO_NAME)
        implementer = scenario.get("implementer", "carter-engineer")
        system = (agents_dir / f"{implementer}.md").read_text()

        transcript = _call_model(system, _plan_prompt(scenario))
        result = grade_transcript(scenario, transcript)

        if os.environ.get("EVAL_RECORD") == "1":
            _record_fixture(transcript, result)

        assert result.adherence >= PASS_BAR_MIN_ADHERENCE, (
            f"live Sonnet adherence {result.adherence:.2%} below the 90% bar; "
            f"missed: {result.failed_ids}"
        )
        assert result.critical_failures == 0, (
            f"live Sonnet run has critical-step failures: {result.failed_ids}"
        )


def _record_fixture(transcript: str, result) -> None:  # noqa: ANN001 — AdherenceResult
    """Overwrite the recorded fixture with the fresh live transcript + grade."""
    from evals.metrics import DEFAULT_MODEL

    fixture = {
        "scenario": _SCENARIO_NAME,
        "model": os.environ.get("EVAL_MODEL", DEFAULT_MODEL),
        "provider": "live",
        "note": "Re-recorded via EVAL_RECORD=1; the offline replay grades this transcript.",
        "transcript": transcript,
        "adherence": result.adherence,
        "critical_failures": result.critical_failures,
        "passed": result.passed,
    }
    (_FIXTURES / "implementer_adherence_sonnet.json").write_text(
        json.dumps(fixture, indent=2) + "\n"
    )
