"""The frozen gate corpus (RFC-0007 C.4.3) run in-process through ``carter.gate.check``.

Plan 004 step 17 wrote these first: they fail until the gate exists (steps 18-21) and every
later change to the gate must keep them green. A deny case names the rule id it must raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carter import gate  # noqa: I001 - fails with ImportError until step 18
from gate import corpus

CASES = corpus.load()
WORKFLOW = corpus.load(corpus.WORKFLOW)


def run(case: dict, tmp_path: Path):
    cwd = corpus.apply_setup(case, tmp_path)
    return gate.check(
        corpus.fill(case["command"], tmp_path), cwd, tuple(case.get("skip_groups", ()))
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_corpus(case: dict, tmp_path: Path) -> None:
    decision = run(case, tmp_path)
    assert decision.decision == case["expect"], f"{case['command']!r}: {decision}"
    if case["expect"] == "deny":
        assert decision.rule == case["rule"], f"{case['command']!r}: {decision}"
        assert decision.message and decision.message.startswith(
            "Refused by the Carter command gate (rule `"
        )
    else:
        assert decision.rule is None and decision.message is None


@pytest.mark.parametrize("case", WORKFLOW, ids=lambda c: c["id"])
def test_workflow_corpus_has_no_false_positive(case: dict, tmp_path: Path) -> None:
    decision = run(case, tmp_path)
    assert decision.decision == "allow", f"{case['command']!r}: {decision}"


def test_the_corpus_is_big_enough_and_each_case_says_why() -> None:
    deny = [c for c in CASES if c["expect"] == "deny"]
    allow = [c for c in CASES if c["expect"] == "allow"]
    assert len(deny) >= 16 + 20 and len(allow) >= 20
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert all(c["why"].strip() and "\n" not in c["why"] for c in CASES)
    assert all(c["rule"] for c in deny) and not any("rule" in c for c in allow)
    assert len(WORKFLOW) >= 15


def test_the_residual_choice_is_pinned_as_allowed() -> None:
    """D67: shell writes to the other paths of section 4.5 are allowed, on purpose."""
    residual = {c["id"] for c in CASES if c.get("residual")}
    assert {
        "res-global-opencode-config", "res-gitconfig", "res-xdg-git", "res-git-hooks",
        "res-git-config", "res-project-opencode-dir", "res-project-opencode-json",
    } <= residual  # fmt: skip
    assert all(c["expect"] == "allow" for c in CASES if c.get("residual"))
