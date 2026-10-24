"""Implementer-adherence grader (ADR-0010 D9).

Grades how faithfully an implementer transcript executes a thinker-produced plan. The
grading is deterministic and evidence-pattern based (no model call), so a recorded
transcript replays identically offline — the per-PR gate never touches the live API.

A plan carries `must_haves.truths` (gradeable claims) and `acceptance` checks. Each item
is satisfied against the transcript by one of:

  - ``evidence_any``  — at least one pattern present (case-insensitive substring)
  - ``evidence_all``  — every pattern present
  - ``evidence_none`` — no pattern present (an intent the implementer must NOT violate)

`adherence` = fraction of `must_haves.truths` satisfied. `critical_failures` = number of
items flagged ``critical: true`` (across truths AND acceptance) that are NOT satisfied —
a named-file touch, an acceptance check, or a load-bearing intent whose miss breaks the
plan's truths.

Pass-bar (D9): ``adherence >= 0.90`` AND ``critical_failures == 0``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The D9 pass-bar: >= 90% of must_haves satisfied AND 0 critical-step failures.
PASS_BAR_MIN_ADHERENCE = 0.90


@dataclass
class AdherenceResult:
    """The graded outcome of one implementer transcript against one plan."""

    adherence: float  # fraction of must_haves.truths satisfied (0.0–1.0)
    critical_failures: int  # critical items (truths + acceptance) NOT satisfied
    passed: bool  # adherence >= bar AND critical_failures == 0
    satisfied_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)


def load_scenario(path: Path, name: str) -> dict:
    """Load one named scenario from a scenarios YAML file."""
    scenarios = yaml.safe_load(Path(path).read_text())
    for scenario in scenarios:
        if scenario.get("name") == name:
            return scenario
    raise KeyError(f"scenario {name!r} not found in {path}")


def _scoped(transcript: str, marker: str) -> str:
    """The transcript slice AFTER the last occurrence of ``marker`` (case-insensitive).

    Used to grade an item against only the delimited FINAL artifact (e.g. the outward
    release note the narrator emits) rather than the whole transcript, so an agent's
    internal reasoning — a redaction audit that legitimately restates original values —
    does not count against an ``evidence_none`` leak check. If the marker is absent, the
    slice is empty: the artifact wasn't produced in the required delimited form, so an
    ``evidence_any`` fails and an ``evidence_none`` trivially holds over empty text — the
    caller pairs the scoped leak check with an unscoped "marker present" must_have.
    """
    idx = transcript.lower().rfind(marker.lower())
    return "" if idx == -1 else transcript[idx + len(marker) :]


def _satisfied(item: dict, transcript: str) -> bool:
    """Whether a single gradeable item's evidence condition holds against ``transcript``.

    Case-insensitive substring matching. Exactly one of ``evidence_any`` /
    ``evidence_all`` / ``evidence_none`` is expected per item. An optional ``scope``
    marker restricts matching to the transcript slice after that marker's last occurrence
    (grade only the delimited final artifact).
    """
    text = _scoped(transcript, item["scope"]) if "scope" in item else transcript
    hay = text.lower()
    if "evidence_any" in item:
        return any(p.lower() in hay for p in item["evidence_any"])
    if "evidence_all" in item:
        return all(p.lower() in hay for p in item["evidence_all"])
    if "evidence_none" in item:
        return not any(p.lower() in hay for p in item["evidence_none"])
    raise ValueError(f"item {item.get('id')!r} has no evidence_any/all/none clause")


def grade_transcript(scenario: dict, transcript: str) -> AdherenceResult:
    """Grade ``transcript`` against ``scenario``'s plan, returning an ``AdherenceResult``.

    `adherence` counts only `must_haves.truths`. `critical_failures` counts every
    `critical: true` item across BOTH `must_haves.truths` and `acceptance` (an acceptance
    check is, by construction, a critical surface — a missed one is a critical failure).
    """
    truths = scenario.get("must_haves", {}).get("truths", [])
    acceptance = scenario.get("acceptance", [])

    satisfied_ids: list[str] = []
    failed_ids: list[str] = []
    critical_failures = 0

    sat_truths = 0
    for truth in truths:
        ok = _satisfied(truth, transcript)
        (satisfied_ids if ok else failed_ids).append(truth["id"])
        if ok:
            sat_truths += 1
        elif truth.get("critical"):
            critical_failures += 1

    # Acceptance checks contribute to critical_failures only (not to the adherence
    # fraction, which is the must_haves ratio per D9).
    for check in acceptance:
        ok = _satisfied(check, transcript)
        (satisfied_ids if ok else failed_ids).append(check["id"])
        if not ok and check.get("critical"):
            critical_failures += 1

    adherence = (sat_truths / len(truths)) if truths else 0.0
    passed = adherence >= PASS_BAR_MIN_ADHERENCE and critical_failures == 0
    return AdherenceResult(
        adherence=adherence,
        critical_failures=critical_failures,
        passed=passed,
        satisfied_ids=satisfied_ids,
        failed_ids=failed_ids,
    )
