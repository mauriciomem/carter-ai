"""The corpus is normative: changing an expected result is a reviewed change.

If this fails you edited ``tests/data/gate_corpus.yaml``. Loosening a case to make the gate pass
is not allowed; adding cases, or fixing a case that was wrong, is: update ``FROZEN_SHA256`` in the
same change and say why in the commit message.
"""

from __future__ import annotations

from gate import corpus

# The hash covers every field but ``why``. The counts only grow.
FROZEN_SHA256 = "182817b3e94cf29aa30e5299c5328cb19e180e8da9f19f8267a803a914952242"
FROZEN_COUNTS = {"deny": 240, "allow": 140}


def test_the_corpus_hash_is_the_reviewed_one() -> None:
    cases = corpus.load()
    assert corpus.canonical_hash(cases) == FROZEN_SHA256


def test_the_counts_only_grow() -> None:
    cases = corpus.load()
    for kind, floor in FROZEN_COUNTS.items():
        assert sum(c["expect"] == kind for c in cases) >= floor
