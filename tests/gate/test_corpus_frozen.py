"""The corpus is normative (RFC C.4.3): changing an expected result is a reviewed change.

If this fails you edited ``tests/data/gate_corpus.yaml``. Loosening a case to make the gate pass
is not allowed; adding cases, or fixing a case that was wrong, is: update ``FROZEN_SHA256`` in the
same change and say why in the commit message and in ``notes.md``.
"""

from __future__ import annotations

from gate import corpus

# Reviewed change before the first commit (step 21): +3 nested-command deny cases (git rebase -x,
# bisect run, submodule foreach); fz-cred-glob got a home_dirs setup (a glob needs the directory
# to exist); x-push-proc-subst now expects dynamic-command (a shell whose script is a <(...)).
# Slice B (plan 007 step 21): +4 deny cases (python -m carter.broker_cli in both spellings, an
# interpreter program importing carter.broker, `carter broker`) and +1 allow case (another module);
# the security review (step 22) added the audit store as a control path: +1 deny (a forged line),
# +1 allow (reading the audit).
# Slice CI-E (plan 008): +1 deny (`carter ci install` is human-only), +1 allow (`carter ci review`).
# D72 (PRs are allowed): `carter pr` is gone (-1 deny); `gh pr create` stops being a deny
# example, so `gh pr merge` takes its place; +2 deny (`gh pr close`, `gh pr review`) and +3 allow
# (`gh pr create`, `gh pr edit`, `gh pr comment`).
FROZEN_SHA256 = "c0f7f305e1d4a3bc4dce8e0d92dfbd28806496eda7fa81c0dd0dc262456998f9"
FROZEN_COUNTS = {"deny": 240, "allow": 140}


def test_the_corpus_hash_is_the_reviewed_one() -> None:
    cases = corpus.load()
    assert corpus.canonical_hash(cases) == FROZEN_SHA256


def test_the_counts_only_grow() -> None:
    cases = corpus.load()
    for kind, floor in FROZEN_COUNTS.items():
        assert sum(c["expect"] == kind for c in cases) >= floor
