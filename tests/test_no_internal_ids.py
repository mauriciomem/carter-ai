"""No tracked file names a project-internal id.

Carter's history lives in git and in the local, untracked ``docs/adr`` and ``docs/rfcs``; code,
tests, skills, templates and public docs describe what the software does now. A decision number
(``D45``), an RFC or ADR number, a plan, step, slice or spike number, a freeze or erratum id, a
section pointer into a design document or a letter-number id (``K2``, ``H7``, ``B9``) tells the
reader to look something up they cannot see. Say it in words, or delete it.

There is no changelog file: release notes are generated from commit messages and live on the
GitHub Releases page.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKIP_PREFIXES = ("docs/adr/", "docs/rfcs/", "evals/fixtures/")  # fixtures: recorded model output
SKIP_FILES = {
    "uv.lock",
    "tests/test_no_internal_ids.py",  # defines the patterns
    "tests/test_help.py",  # defines its own, broader pattern for `--help` texts
}
SKIP_SUFFIXES = (".png", ".svg", ".gif", ".jpg", ".pyc", ".bundle")

PATTERNS = {
    "decision id": r"\bD\d{2}\b",
    "RFC or ADR number": r"\bRFC-(?!0001\b|NNNN)\d{4}\b|\bADR-\d{4}\b",
    "design-document section": r"§\s?\d|\bApp(?:endix)? [A-C]\b|\bC\.\d\b",
    "plan number": r"\b[Pp]lan 00\d\b(?!-)|\b00\d-(?:llm-attribution|slice-)",
    "slice": r"\b[Ss]lices?\s+(?:\d|1G|2[abc]|B\b|CI-E)|\bCI-E\b|\b1G\b|\b2[abc]\b(?![\w.-])",
    "spike": r"\b[Ss]pike\b",
    "research report": r"\b[Rr]eport \d{2}\b|\b(?:maestro|architect) decision\b",
    "freeze or erratum": r"\bfreeze\b|\berrat(?:a|um)\b",
    "letter-number id": (
        r"\b(?!G2\b|K1\b)[GHK]\d{1,2}\b|\bB\d{1,2}\b|\bT(?:[3-9]|\d{2})\b"
        r"|\b[CEF]\d{2}\b|\bO\d\b|\bA[1-9]\b"
    ),
}
# "step 33" is a plan step in code and tests; user docs and skills use "step 1" for a workflow
CODE_ONLY = {"plan step": r"\b[Ss]tep (?:\d{2,}|[3-9])\b"}
CODE_DIRS = ("carter/", "tests/", "evals/", ".github/")
CODE_SUFFIXES = (".py", ".ts", ".sh", ".yml")


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [
        f
        for f in out
        if f not in SKIP_FILES
        and not f.startswith(SKIP_PREFIXES)
        and not f.endswith(SKIP_SUFFIXES)
        and (REPO / f).is_file()
    ]


def hits(path: str) -> list[str]:
    try:
        text = (REPO / path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    rules = dict(PATTERNS)
    if path.startswith(CODE_DIRS) and path.endswith(CODE_SUFFIXES):
        rules.update(CODE_ONLY)
    found = []
    for number, line in enumerate(text.split("\n"), 1):
        for name, rx in rules.items():
            if re.search(rx, line):
                found.append(f"{path}:{number}: {name}: {line.strip()[:110]}")
    return found


def test_no_tracked_file_names_an_internal_id() -> None:
    offenders = [hit for path in tracked() for hit in hits(path)]
    assert offenders == [], "\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "line",
    [
        "# see D45",
        "RFC-0007 says",
        "ADR-0016 D4",
        "the rule of §4.5",
        "App C.1",
        "plan 007 step 4",
        "a slice 2a change",
        "Slice B",
        "spike 4",
        "freeze G3",
        "the K2 rule",
        "(H7)",
        "B9",
        "T12",
        "E11: x",
    ],
)
def test_the_patterns_catch_what_they_are_for(line: str) -> None:
    assert any(re.search(rx, line) for rx in PATTERNS.values()), line


@pytest.mark.parametrize(
    "line",
    [
        "tier T2 and group G2",
        "a K1 signature",
        "RFC-0001 and RFC-NNNN are examples",
        "python slices: items[1:3]",
        "OWASP A01 and S3 buckets",
        "a latency regression",
        "step 1 of the workflow",
    ],
)
def test_the_patterns_leave_ordinary_words_alone(line: str) -> None:
    assert not any(re.search(rx, line) for rx in PATTERNS.values()), line
