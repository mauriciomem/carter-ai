"""Shared helpers for the ``test_docs_*.py`` files: read a doc, cut a section, compare options."""

from __future__ import annotations

import re
from pathlib import Path

from click.testing import CliRunner

from carter.cli import main

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
LOCAL_ONLY = {"adr", "rfcs"}  # kept out of the public tree


def text(rel: str) -> str:
    """A file under ``docs/``."""
    return (DOCS / rel).read_text(encoding="utf-8")


def norm(s: str) -> str:
    """Collapse whitespace so a phrase can wrap across lines in the Markdown."""
    return " ".join(s.split())


def section(doc: str, heading: str, level: str = "##") -> str:
    """The body of ``<level> heading`` up to the next heading of the same or higher rank."""
    start = doc.index(f"\n{level} {heading}\n")
    rest = doc[start + 1 :]
    nxt = re.search(rf"\n#{{1,{len(level)}}} ", rest[5:])
    return rest if not nxt else rest[: nxt.start() + 5]


def help_options(*command: str) -> set[str]:
    """The long options ``carter <command> --help`` lists."""
    out = CliRunner().invoke(main, [*command, "--help"]).output
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", out)) - {"--help", "--base-dir"}


def documented(block: str) -> set[str]:
    """The long options a Markdown block names in backticks."""
    return set(re.findall(r"`(?:-\w, )?(--[a-z][a-z0-9-]+)", block)) - {"--help", "--base-dir"}


def codes_in(block: str) -> set[str]:
    """Every ``E-...`` code a block names."""
    return set(re.findall(r"E-[A-Z0-9]+(?:-[A-Z0-9]+)+", block))


def user_docs() -> dict[str, str]:
    """The README and every public doc, by repo-relative path."""
    found = {"README.md": (REPO / "README.md").read_text(encoding="utf-8")}
    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS)
        if not LOCAL_ONLY & set(rel.parts):
            found[f"docs/{rel.as_posix()}"] = path.read_text(encoding="utf-8")
    return found
