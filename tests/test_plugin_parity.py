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
