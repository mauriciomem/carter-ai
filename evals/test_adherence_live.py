"""LIVE adherence eval (ADR-0010 D9).

Sends a thinker-produced plan to the **Sonnet** implementer tier (the agent's system prompt) via
the live API and grades the real transcript with the same deterministic grader the
offline replay uses. This is the BILLED run. It covers every agent moving off Opus →
Sonnet by default: the engineer implementer, plus the narrator and pm.

Cadence: NOT per-PR. It carries the `live` marker (via the shared `test_live` auth
helpers), so the PR gate — which runs `-m "not live"` — never invokes it. It runs on the
weekly `evals-live` cron / `workflow_dispatch`, exactly like the other live evals.

Re-recording fixtures: run with ``EVAL_RECORD=1`` to overwrite each scenario's
``evals/fixtures/<name>_sonnet.json`` with the fresh live transcript + grade, so the
offline replay tracks current Sonnet behavior.
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

# (scenario_file, scenario_name, fixture_file) — the downgrade-gate registry, mirroring
# evals/test_adherence.py. Each agent moving to Sonnet by default records one fixture.
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


def _plan_prompt(scenario: dict) -> str:
    """Render the thinker plan as the user message handed to the agent.

    Role-agnostic: the agent's own system prompt (its rendered `carter-<role>.md`) decides
    HOW it responds — the engineer writes code, the narrator drafts redacted content, the
    pm produces a plan. This prompt only hands over the plan, its steps, and the required
    outcomes, and asks the agent to work directly without tools (so the transcript is the
    graded artifact).
    """
    plan = scenario["plan"]
    steps = "\n".join(f"- {s}" for s in plan["steps"])
    must = "\n".join(f"- {t['id']}" for t in scenario["must_haves"]["truths"])
    source = plan.get("source_material")
    source_block = f"\n## Source material\n{source}\n" if source else ""
    return (
        "Execute this plan, following your role and instructions. Produce the deliverable "
        "directly in your reply, with explicit detail — do not use any tools.\n\n"
        f"# Plan: {plan['title']}\n\n"
        f"Objective: {plan['objective']}\n"
        f"{source_block}\n"
        f"## Steps\n{steps}\n\n"
        f"## Required outcomes (must_haves)\n{must}\n"
    )


@pytest.mark.parametrize(
    "scenario_file,scenario_name,fixture_file",
    _DOWNGRADE_SCENARIOS,
    ids=[s[1] for s in _DOWNGRADE_SCENARIOS],
)
class TestLiveDowngradeAdherence:
    """Each downgraded agent's Sonnet run must clear >=90% must_haves + 0 critical
    failures. `EVAL_RECORD=1` writes the fixture the offline per-PR gate replays.
    """

    def test_sonnet_clears_the_bar(
        self,
        agents_dir: Path,
        scenarios_dir: Path,
        scenario_file: str,
        scenario_name: str,
        fixture_file: str,
    ) -> None:
        scenario = load_scenario(scenarios_dir / scenario_file, scenario_name)
        agent = scenario.get("implementer", "carter-engineer")
        system = (agents_dir / f"{agent}.md").read_text()

        transcript = _call_model(system, _plan_prompt(scenario))
        result = grade_transcript(scenario, transcript)

        if os.environ.get("EVAL_RECORD") == "1":
            _record_fixture(scenario_name, fixture_file, transcript, result)

        assert result.adherence >= PASS_BAR_MIN_ADHERENCE, (
            f"{scenario_name}: live Sonnet adherence {result.adherence:.2%} below the 90% "
            f"bar; missed: {result.failed_ids}"
        )
        assert result.critical_failures == 0, (
            f"{scenario_name}: live Sonnet run has critical-step failures: {result.failed_ids}"
        )


def _record_fixture(scenario_name: str, fixture_file: str, transcript: str, result) -> None:  # noqa: ANN001 — AdherenceResult
    """Overwrite a scenario's recorded fixture with the fresh live transcript + grade.

    The stored ``model`` is the CANONICAL Carter id (``claude-sonnet-4-6``, hyphen), which
    the offline replay asserts — independent of any provider-specific id passed via
    ``EVAL_MODEL`` when recording.
    """
    from evals.metrics import DEFAULT_MODEL

    fixture = {
        "scenario": scenario_name,
        "model": DEFAULT_MODEL,  # canonical hyphen id; see docstring re transport id
        "provider": "live",
        "note": "Re-recorded via EVAL_RECORD=1; the offline replay grades this transcript.",
        "transcript": transcript,
        "adherence": result.adherence,
        "critical_failures": result.critical_failures,
        "passed": result.passed,
    }
    (_FIXTURES / fixture_file).write_text(json.dumps(fixture, indent=2) + "\n")
