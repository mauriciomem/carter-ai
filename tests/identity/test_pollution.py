"""AD1, pollution and ``GIT_CONFIG_COUNT`` against the shared golden vectors (plan 004 step 10).

The same vector file is consumed by the TypeScript core tests (``tests/plugin``) and, in step 22,
by the ``carter-guard`` sh tests. The Python functions are the oracle.
"""

from __future__ import annotations

import pytest

from carter.identity.pollution import COUNT_CAP, count_state, pollution
from carter.identity.rules import is_agent, load_rules, warn_hits
from identity import vectors

V = vectors.load()
HOME = V["home"]


def ids(cases: list[dict]) -> list[str]:
    return [c["name"] for c in cases]


class TestAd1:
    @pytest.mark.parametrize("case", V["ad1"], ids=ids(V["ad1"]))
    def test_table(self, case: dict) -> None:
        assert is_agent(case["env"]) is case["agent"]

    def test_every_agent_signal_is_covered_by_a_vector(self) -> None:
        named = {k for case in V["ad1"] for k in case["env"]}
        assert set(load_rules().agent_signals) | set(load_rules().human_signals) <= named


class TestPollution:
    @pytest.mark.parametrize("case", V["pollution"], ids=ids(V["pollution"]))
    def test_table(self, case: dict) -> None:
        names = pollution(case["env"], HOME)
        assert names == case["names"]
        assert bool(names) is case["polluted"]

    def test_tokens_only_warn(self) -> None:
        env = {"GH_TOKEN": "x", "GITHUB_TOKEN": "y"}
        assert pollution(env, HOME) == []
        assert warn_hits(env) == ["GH_TOKEN", "GITHUB_TOKEN"]

    def test_values_are_never_returned(self) -> None:
        env = {"GIT_SSH_COMMAND": "ssh -o IdentityAgent=none -o SECRET-VALUE=1"}
        assert pollution(env, HOME) == ["GIT_SSH_COMMAND"]

    def test_explicit_pair_markers_replace_the_default(self) -> None:
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": "c"}
        assert pollution(env, HOME, pair_markers=[("a.b", "c")]) == [
            "GIT_CONFIG_KEY_n/GIT_CONFIG_VALUE_n"
        ]
        assert pollution(env, HOME, pair_markers=[]) == []


class TestCount:
    @pytest.mark.parametrize("case", V["count"], ids=ids(V["count"]))
    def test_table(self, case: dict) -> None:
        got = count_state(vectors.expand(case["env"]))
        assert (got.state, got.n, got.reason) == (case["state"], case["n"], case["reason"])

    def test_polluted_always_restarts_at_zero(self) -> None:
        assert all(c["n"] == 0 for c in V["count"] if c["state"] == "polluted")

    def test_the_cap_is_inclusive(self) -> None:
        assert COUNT_CAP == 1000
        assert {c["name"]: c["state"] for c in V["count"]}["at the cap"] == "ok"
        assert {c["name"]: c["state"] for c in V["count"]}["over the cap"] == "polluted"

    def test_unicode_digits_are_not_digits(self) -> None:
        assert count_state({"GIT_CONFIG_COUNT": "١"}).reason == "malformed"  # Arabic-indic one
