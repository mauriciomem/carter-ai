"""Every item of ``g2_rules.json`` is enforced by the gate (no list entry can silently go dead)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gate.helpers import rule_of

DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "carter/identity/g2_rules.json").read_text("utf-8")
)
CLASSES = {c["id"]: c for c in DATA["forbidden"]}


def items(rule: str, *extra_keys: str) -> list[str]:
    cls = CLASSES[rule]
    return list(cls["items"]) + [x for k in extra_keys for x in cls.get(k, [])]


@pytest.mark.parametrize("key", items("config-flags", "gate_keys"))
def test_every_config_key_pattern_is_refused_after_dash_c(key: str) -> None:
    sample = key.replace("*", "x")
    assert rule_of(f"git -c {sample}=v status") == "config-flags", key


@pytest.mark.parametrize("verb", items("plumbing"))
def test_every_plumbing_verb_is_refused(verb: str) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert rule_of(f"git {verb} refs/heads/x {sha}") == "plumbing", verb


@pytest.mark.parametrize("verb", CLASSES["push-verbs"]["gate_verbs"])
def test_every_push_verb_is_refused(verb: str) -> None:
    assert rule_of(f"git {verb} x") == "push-verbs", verb


@pytest.mark.parametrize("item", items("other-verbs", "gate_extra"))
def test_every_other_verb_is_refused(item: str) -> None:
    assert rule_of(item) == "other-verbs", item


@pytest.mark.parametrize("item", items("human-only-carter"))
def test_every_human_only_carter_verb_is_refused(item: str) -> None:
    words = item.split()
    if len(words) > 2 and "/" in words[2]:
        for sub in words[2].split("/"):
            assert rule_of(f"{words[0]} {words[1]} {sub}") == "human-only-carter", item
    else:
        assert rule_of(item.replace("*", "anything")) == "human-only-carter", item


@pytest.mark.parametrize("item", items("commit-flags"))
def test_every_commit_flag_is_refused(item: str) -> None:
    if item in ("-S", "--gpg-sign"):
        assert rule_of(f"git commit {item} -m x") is None  # bare forms are allowed (RFC C.4.1)
        return
    flag = item.replace("<arg>", "X")
    assert rule_of(f"git commit {flag} -m x") == "commit-flags", item


@pytest.mark.parametrize("item", items("staging"))
def test_every_staging_form_is_refused(item: str) -> None:
    assert rule_of(item) == "staging", item


@pytest.mark.parametrize("item", items("git-config-writes"))
def test_every_git_config_write_form_is_refused(item: str) -> None:
    sample = item.replace("<key>", "a.b").replace("<value>", "v")
    if "<" not in item:
        value_first = " f" if item.endswith("--file") else ""  # --file takes a path
        sample += f"{value_first} a.b v"  # a scope flag with a key and a value is the write
    assert rule_of(sample) == "git-config-writes", item


@pytest.mark.parametrize("item", items("control-files", "gate_extra_commands"))
def test_every_control_file_writer_is_refused(item: str) -> None:
    name = item.split()[0]
    if name in ("dd", "chown", "chgrp"):
        return  # take of= / an owner first: covered by test_paths
    sample = item if " " in item else f"{name} x"
    cmd = f"{sample} ~/.carter/isolation.json"
    assert rule_of(cmd) == "control-files", item


@pytest.mark.parametrize("verb", [e["verb"] for e in DATA["gh_read_allowlist"]])
def test_every_allowlisted_gh_verb_passes(verb: str) -> None:
    assert rule_of(f"gh {verb}") is None


def test_every_hint_id_is_a_rule_the_gate_can_name() -> None:
    ids = {c["id"] for c in DATA["forbidden"]} | {r["id"] for r in DATA["gate_rules"]}
    assert {"dynamic-command", "interpreter-git", "git-alias", "gate-input"} <= ids
    assert len(ids) == 15


@pytest.mark.parametrize("pair", CLASSES["push-verbs"]["gate_pairs"])
def test_every_extra_push_pair_is_refused(pair: list[str]) -> None:
    assert rule_of(f"git {pair[0]} {pair[1]} x") == "push-verbs", pair
    assert rule_of(f"git {pair[0]} status", cwd="/tmp") is None, pair
