"""The corpus is normative: changing an expected result is a reviewed change.

If this fails you edited ``tests/data/gate_corpus.yaml``. Loosening a case to make the gate pass
is not allowed; adding cases, or fixing a case that was wrong, is: update ``FROZEN_SHA256`` in the
same change and say why in the commit message.
"""

from __future__ import annotations

from gate import corpus

# The hash covers every field but ``why``. The counts only grow.
FROZEN_SHA256 = "fa64b4ad9608eae2a8f5a85561a6935896000b3fb380bd7b0ab47802537e4b78"
FROZEN_COUNTS = {"deny": 298, "allow": 159}


def test_the_corpus_hash_is_the_reviewed_one() -> None:
    cases = corpus.load()
    assert corpus.canonical_hash(cases) == FROZEN_SHA256


def test_the_counts_only_grow() -> None:
    cases = corpus.load()
    for kind, floor in FROZEN_COUNTS.items():
        assert sum(c["expect"] == kind for c in cases) >= floor
