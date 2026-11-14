"""The corpus is normative: changing an expected result is a reviewed change.

If this fails you edited ``tests/data/gate_corpus.yaml``. Loosening a case to make the gate pass
is not allowed; adding cases, or fixing a case that was wrong, is: update ``FROZEN_SHA256`` in the
same change and say why in the commit message.
"""

from __future__ import annotations

from gate import corpus

# The hash covers every field but ``why``. The counts only grow.
FROZEN_SHA256 = "2cfca0b4d84d664db248bf1721abab3d9af0bf8bc37803e9ee8ae96ebc9126e0"
FROZEN_COUNTS = {"deny": 295, "allow": 159}


def test_the_corpus_hash_is_the_reviewed_one() -> None:
    cases = corpus.load()
    assert corpus.canonical_hash(cases) == FROZEN_SHA256


def test_the_counts_only_grow() -> None:
    cases = corpus.load()
    for kind, floor in FROZEN_COUNTS.items():
        assert sum(c["expect"] == kind for c in cases) >= floor
