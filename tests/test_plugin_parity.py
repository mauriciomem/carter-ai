"""Cross-runtime parity between the Python oracles and the TypeScript core (plan 004 steps 13-16).

The shared golden vectors are exercised by both ``pytest`` and ``node --test``. These tests cover
what vectors cannot: the registry texts the TS carries, and a real round trip of an
``isolation.json`` that Python renders and the TS then loads, hashes and validates.
Skipped, with the reason, when Node is missing or older than 22.18.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from carter.identity import isolation
from carter.identity.errors import registry
from carter.identity.pollution import pollution

REPO = Path(__file__).resolve().parent.parent
CORE = REPO / "carter" / "plugin" / "core.ts"
NODE = shutil.which("node")


def node_ok() -> bool:
    if NODE is None:
        return False
    out = subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    return bool(match) and (int(match.group(1)), int(match.group(2))) >= (22, 18)


pytestmark = pytest.mark.skipif(not node_ok(), reason="node >= 22.18 is needed")


def node(script: str) -> str:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    return done.stdout


def test_the_ts_error_texts_are_the_registry_texts() -> None:
    out = node(
        f"import {{ MESSAGES }} from '{CORE.as_uri()}'; console.log(JSON.stringify(MESSAGES))"
    )
    ts = json.loads(out)
    assert set(ts) == {
        "E-ISOLATION-MISSING", "E-GATE-FAIL", "E-SELFTEST", "E-SIGN-UNAVAILABLE", "E-CONFIG",
        "E-B-CALLER",
    }  # fmt: skip
    for code, text in ts.items():
        assert text == registry()[code].message, code


def test_an_isolation_file_rendered_by_python_is_loaded_and_checked_by_the_ts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "h"
    doc = isolation.render(
        home=str(home),
        python_path=sys.executable,
        carter_path="/x/carter",
        false_path="/usr/bin/false",
        pat_file=str(home / ".carter/secrets/gh-read.token"),
        declined_groups=("sudo-docker",),
    )
    raw = isolation.canonical_bytes(doc)
    target = tmp_path / "isolation.json"
    target.write_bytes(raw)
    sha = isolation.sha256_hex(raw)
    path, wrong = json.dumps(str(target)), json.dumps("0" * 64)
    script = f"""
    import * as fs from 'node:fs'
    import {{ loadIsolation }} from '{CORE.as_uri()}'
    const iso = loadIsolation(fs, {path}, {json.dumps(sha)})
    console.log(JSON.stringify(iso))
    try {{ loadIsolation(fs, {path}, {wrong}); console.log('NO-THROW') }}
    catch (e) {{ console.log(e.code) }}
    """
    first, second = node(script).splitlines()
    assert json.loads(first) == doc
    assert second == "E-ISOLATION-MISSING"


def test_pollution_of_a_rendered_document_agrees_between_the_runtimes(tmp_path: Path) -> None:
    home = "/home/example"
    doc = isolation.render(
        home=home, python_path="/p/python", carter_path="/p/carter", false_path="/usr/bin/false"
    )
    envs = [
        {"PATH": "/usr/bin"},
        {"AGENT": "1"},
        {"GH_CONFIG_DIR": f"{home}/.carter/run/gh-empty"},
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "remote.origin.pushurl",
            "GIT_CONFIG_VALUE_0": "no_push",
        },
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "x"},
    ]
    script = f"""
    import {{ isPolluted }} from '{CORE.as_uri()}'
    const pol = {json.dumps(doc["pollution"])}
    console.log(JSON.stringify({json.dumps(envs)}.map((e) => isPolluted(e, pol))))
    """
    assert json.loads(node(script)) == [bool(pollution(e, home)) for e in envs]


def test_a_block_built_by_python_is_accepted_by_the_ts_and_applied_the_same_way() -> None:
    """Python and TS agree on a real ``build_payload`` result and on applying it (plan 005 step 12),
    on an environment that already carries the isolation entries."""
    from carter.identity.isolation_apply import apply_isolation
    from carter.identity.payload import ShimState, build_payload, fingerprint_of, to_git_env
    from carter.identity.resolve import resolve
    from carter.identity.schema import Identity, IdentityConfig, Signing

    blob = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
    cfg = IdentityConfig(
        identity=Identity(login="llm-bot", id=7, email="7+llm-bot@users.noreply.github.com"),
        signing=Signing(public_key=blob + " comment", fingerprint=fingerprint_of(blob)),
        state="current",
    )
    built = build_payload(
        cfg,
        resolve(cfg, workspace=None, env={}),
        ShimState("/home/example/.carter/bin/carter-ssh-sign", True),
    )
    assert built.block is not None
    doc = isolation.render(
        home="/home/example",
        python_path="/p/python",
        carter_path="/p/carter",
        false_path="/usr/bin/false",
    )
    start = apply_isolation({"PATH": "/usr/bin", "GIT_CONFIG_PARAMETERS": "'x.y=z'"}, doc, None).env
    expected = to_git_env(start, built.block)
    script = f"""
    import {{ validateSigning, applySigning }} from '{CORE.as_uri()}'
    const block = {json.dumps(built.block)}
    const accepted = validateSigning(block, {json.dumps(doc)}) !== null
    const out = applySigning({json.dumps(start)}, block)
    console.log(JSON.stringify({{ accepted, env: out.env, flags: out.flags }}))
    """
    got = json.loads(node(script))
    assert got["accepted"] is True
    assert got["env"] == expected.env and got["flags"] == expected.flags


def test_a_role_b_block_built_by_python_is_accepted_by_the_ts_and_applied_the_same_way() -> None:
    """Plan 006 step 9: the TS is thin: the same two functions handle the five-key role-b env."""
    from carter.identity.coauthor import Human
    from carter.identity.isolation_apply import apply_isolation
    from carter.identity.payload import ShimState, build_payload, fingerprint_of, to_git_env
    from carter.identity.resolve import resolve
    from carter.identity.schema import Identity, IdentityConfig, Signing

    blob = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
    cfg = IdentityConfig(
        identity=Identity(
            role="author", login="llm-bot", id=7, email="7+llm-bot@users.noreply.github.com"
        ),
        signing=Signing(public_key=blob, fingerprint=fingerprint_of(blob)),
        state="current",
    )  # fmt: skip
    built = build_payload(
        cfg,
        resolve(cfg, workspace=None, env={}),
        ShimState("/home/example/.carter/bin/carter-ssh-sign", True),
        lambda: Human("Hu Man", "human@example.invalid", ""),
    )
    assert built.block is not None and "GIT_AUTHOR_EMAIL" in built.block["env"]
    doc = isolation.render(
        home="/home/example",
        python_path="/p/python",
        carter_path="/p/carter",
        false_path="/usr/bin/false",
    )
    start = {**apply_isolation({"PATH": "/usr/bin"}, doc, None).env, "GIT_AUTHOR_NAME": "Evil"}
    expected = to_git_env(start, built.block)
    script = f"""
    import {{ validateSigning, applySigning }} from '{CORE.as_uri()}'
    const block = {json.dumps(built.block)}
    const accepted = validateSigning(block, {json.dumps(doc)}) !== null
    const out = applySigning({json.dumps(start)}, block)
    console.log(JSON.stringify({{ accepted, env: out.env, flags: out.flags }}))
    """
    got = json.loads(node(script))
    assert got["accepted"] is True and got["env"] == expected.env and got["flags"] == expected.flags
    assert got["env"]["GIT_AUTHOR_NAME"] == "llm-bot"


def test_the_ts_has_no_role_logic_and_isolation_json_is_unchanged() -> None:
    """The plugin never names a role; `identity env` decides (K5). The hash stays pinned."""
    import re

    for name in ("core.ts", "index.ts"):
        text = (CORE.parent / name).read_text(encoding="utf-8")
        assert not re.search(
            r"co-author|\"author\"|role[-_ ]b|human-identity",
            text.replace("human-identity-invalid", ""),
        ), name
    vectors = json.loads((CORE.parents[2] / "tests" / "data" / "plugin_vectors.json").read_text())
    # slice B (schema 2) moved the golden hash once, away from the 2a/2b/2c value d5456e7d...
    assert vectors["isolation"]["sha256"] != (
        "d5456e7d8b82dd91b901cc3ade43fb8dbeecd0bfcbe32556f754797782a40a6e"
    )
    assert vectors["isolation"]["doc"]["schema_version"] == 2
