"""Structure of the shared vector file and the Python oracles for its marker/tier sections."""

from __future__ import annotations

from identity import vectors

V = vectors.load()


def mark(prefix: str, nonce: str, command: str) -> str:
    return f"{prefix}{nonce}\n{command}"


def detect(prefix: str, nonce: str, command: str) -> tuple[bool, str]:
    head = f"{prefix}{nonce}\n"
    return (True, command[len(head) :]) if command.startswith(head) else (False, command)


def test_the_sections_of_g17_are_all_there() -> None:
    assert {"ad1", "pollution", "count", "marker", "isolation", "tier", "status"} <= set(V)


def test_marker_oracle() -> None:
    m = V["marker"]
    for case in m["cases"]:
        assert detect(m["prefix"], m["nonce"], case["command"]) == (
            case["marked"],
            case["stripped"],
        )
    for case in m["mark"]:
        assert mark(m["prefix"], m["nonce"], case["command"]) == case["marked"]


def test_the_marker_format_is_the_c2_one() -> None:
    assert V["marker"]["prefix"] == ": carter_agent_"


def test_tier_cases_cover_every_failure_mode() -> None:
    kinds = {c["outcome"]["kind"] for c in V["tier"]["cases"]}
    assert kinds == {"ok", "exit", "timeout"}
    blocked = {c["name"] for c in V["tier"]["cases"] if c["block"]}
    assert {"the call times out", "invalid JSON", "config error"} <= blocked
    assert not any(c["block"] for c in V["tier"]["cases"] if c["name"] in ("t0", "t1"))


def test_no_vector_holds_a_real_path_or_a_token_shaped_string() -> None:
    text = vectors.PATH.read_text(encoding="utf-8")
    assert "/home/gumbo" not in text and "ghp_" not in text
    import re

    assert not re.search(r"github_pat_[A-Za-z0-9_]{20,}", text)
