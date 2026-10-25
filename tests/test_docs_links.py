"""Relative links and anchors in README.md and docs/** must resolve.

docs/adr/ is local-only (gitignored) and excluded — links into it are not checked.
External (scheme://, mailto:) links are not checked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"

_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.M)


def _doc_files() -> list[Path]:
    files = [REPO / "README.md"]
    files += [p for p in sorted((REPO / "docs").rglob("*.md")) if ADR_DIR not in p.parents]
    return [p for p in files if p.is_file()]


def _strip_code(text: str) -> str:
    return _INLINE_CODE.sub("", _FENCE.sub("", text))


def _slug(heading: str) -> str:
    """GitHub-style heading anchor."""
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # link text only
    h = h.strip().lower().replace("`", "")
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out: set[str] = set()
    for m in _HEADING.finditer(_FENCE.sub("", path.read_text(encoding="utf-8"))):
        base = _slug(m.group(1))
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    out |= set(re.findall(r'<a\s+(?:name|id)="([^"]+)"', path.read_text(encoding="utf-8")))
    return out


def _broken_links(path: Path) -> list[str]:
    problems = []
    for target in _LINK.findall(_strip_code(path.read_text(encoding="utf-8"))):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            continue  # external / mailto
        file_part, _, anchor = target.partition("#")
        dest = (path.parent / file_part).resolve() if file_part else path
        if dest == ADR_DIR or ADR_DIR in dest.parents:
            continue  # local-only, gitignored
        if not dest.exists():
            problems.append(f"{target} (missing file)")
            continue
        if anchor and dest.suffix == ".md" and anchor.lower() not in _anchors(dest):
            problems.append(f"{target} (missing anchor)")
    return problems


@pytest.mark.parametrize("doc", _doc_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_relative_links_resolve(doc: Path) -> None:
    assert _broken_links(doc) == []


def test_link_checker_detects_breakage(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("# Real Heading\n")
    a = tmp_path / "a.md"
    a.write_text(
        "[ok](b.md) [ok](b.md#real-heading) [x](missing.md) [y](b.md#nope) "
        "[ext](https://example.com) `[code](ignored.md)`\n"
    )
    assert _broken_links(a) == ["missing.md (missing file)", "b.md#nope (missing anchor)"]
