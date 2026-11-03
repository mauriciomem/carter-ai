"""Loader for the frozen gate corpus and the setup its cases may ask for."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

DATA = Path(__file__).resolve().parents[1] / "data"
CORPUS = DATA / "gate_corpus.yaml"
WORKFLOW = DATA / "gate_workflow_allow.yaml"


def load(path: Path = CORPUS) -> list[dict[str, Any]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    return list(doc["cases"])


def canonical_hash(cases: list[dict[str, Any]]) -> str:
    text = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fill(text: str, tmp: Path) -> str:
    return text.replace("{tmp}", str(tmp))


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def apply_setup(case: dict[str, Any], tmp: Path) -> str | None:
    """Create what the case asks for under ``tmp``; return the cwd to pass (or None)."""
    setup = case.get("setup", {})
    for rel in setup.get("dirs", []):
        (tmp / rel).mkdir(parents=True, exist_ok=True)
    for rel in setup.get("home_dirs", []):  # under the fixture home
        (Path.home() / rel).mkdir(parents=True, exist_ok=True)
    for link, target in setup.get("symlinks", {}).items():
        os.symlink(os.path.expanduser(fill(target, tmp)), tmp / link)
    aliases = setup.get("aliases", {})
    if aliases:
        # the hermetic fixture points GIT_CONFIG_GLOBAL at a scratch file
        with open(os.environ["GIT_CONFIG_GLOBAL"], "a", encoding="utf-8") as f:
            f.write("[alias]\n" + "".join(f"\t{k} = {v}\n" for k, v in aliases.items()))
    for sub, table in setup.get("aliases_in", {}).items():
        git("init", "-q", sub, cwd=tmp)
        for k, v in table.items():
            git("config", f"alias.{k}", v, cwd=tmp / sub)
    cwd = case.get("cwd")
    return fill(cwd, tmp) if cwd else None
