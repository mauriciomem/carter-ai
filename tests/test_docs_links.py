"""Relative links and anchors in README.md and docs/** must resolve.

docs/adr/ and docs/rfcs/ are local-only (gitignored, absent in CI) and excluded: their
files are not scanned. A tracked doc must not link *into* them either (ADR-0016 D4), as
the link would break on a clean checkout. External (scheme://, mailto:) links are not
checked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"
RFC_DIR = REPO / "docs" / "rfcs"

_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.M)


def _local_only_dirs(repo: Path) -> tuple[Path, ...]:
    """Directories that exist only on the maintainer's machine, resolved under ``repo``."""
    root = repo.resolve()
    return (root / "docs" / "adr", root / "docs" / "rfcs")


def _in_dirs(path: Path, dirs: tuple[Path, ...]) -> bool:
    return any(d == path or d in path.parents for d in dirs)


def _doc_files(repo: Path = REPO) -> list[Path]:
    root = repo.resolve()
    local_only = _local_only_dirs(root)
    files = [root / "README.md"]
    files += [p for p in sorted((root / "docs").rglob("*.md")) if not _in_dirs(p, local_only)]
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


def _broken_links(path: Path, repo: Path = REPO) -> list[str]:
    local_only = _local_only_dirs(repo)
    problems = []
    for target in _LINK.findall(_strip_code(path.read_text(encoding="utf-8"))):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            continue  # external / mailto
        file_part, _, anchor = target.partition("#")
        dest = (path.parent / file_part).resolve() if file_part else path
        if _in_dirs(dest, local_only):
            # Checked before existence: the target is there locally but not in CI.
            problems.append(f"{target} (links into a local-only dir)")
            continue
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


def _make_tree(root: Path, *, with_local_dirs: bool) -> Path:
    """A miniature repo: README.md, docs/guide.md and (optionally) local-only dirs."""
    (root / "docs").mkdir()
    (root / "README.md").write_text("# Title\n[guide](docs/guide.md)\n")
    (root / "docs" / "guide.md").write_text("# Guide\n")
    if with_local_dirs:
        for sub in ("adr", "rfcs/0001-x"):
            (root / "docs" / sub).mkdir(parents=True)
            # A broken link here must never be scanned: these dirs are absent in CI.
            (root / "docs" / sub / "README.md").write_text("[bad](nowhere.md)\n")
    return root


class TestLocalOnlyDirsAreNotScanned:
    @pytest.mark.parametrize("with_local_dirs", [True, False], ids=["present", "absent"])
    def test_scan_is_identical_with_and_without_local_dirs(
        self, tmp_path: Path, with_local_dirs: bool
    ) -> None:
        repo = _make_tree(tmp_path, with_local_dirs=with_local_dirs)

        scanned = [str(p.relative_to(repo)) for p in _doc_files(repo)]

        assert scanned == ["README.md", "docs/guide.md"]

    def test_rfcs_dir_is_excluded_like_adr_dir(self, tmp_path: Path) -> None:
        repo = _make_tree(tmp_path, with_local_dirs=True)

        scanned = {p.relative_to(repo).parts[:2] for p in _doc_files(repo)}

        assert ("docs", "rfcs") not in scanned
        assert ("docs", "adr") not in scanned

    def test_module_constants_point_at_the_repo_dirs(self) -> None:
        assert ADR_DIR == REPO / "docs" / "adr"
        assert RFC_DIR == REPO / "docs" / "rfcs"


class TestTrackedDocsMustNotLinkIntoLocalOnlyDirs:
    """ADR-0016 D4: a tracked doc that links into docs/adr/ or docs/rfcs/ breaks on a
    clean checkout, whether or not the target exists locally."""

    @pytest.mark.parametrize(
        "target",
        [
            "adr/0001-x.md",
            "rfcs/0001-x/README.md",
            "rfcs/README.md#index",
            "adr",
            "./rfcs/",
            "../docs/adr/0001-x.md",
        ],
    )
    @pytest.mark.parametrize("with_local_dirs", [True, False], ids=["present", "absent"])
    def test_link_into_local_only_dir_is_reported(
        self, tmp_path: Path, target: str, with_local_dirs: bool
    ) -> None:
        repo = _make_tree(tmp_path, with_local_dirs=with_local_dirs)
        (repo / "docs" / "guide.md").write_text(f"# Guide\n[why]({target})\n")

        problems = _broken_links(repo / "docs" / "guide.md", repo)

        assert problems == [f"{target} (links into a local-only dir)"]

    def test_plain_text_and_code_mentions_are_fine(self, tmp_path: Path) -> None:
        repo = _make_tree(tmp_path, with_local_dirs=False)
        (repo / "docs" / "guide.md").write_text(
            "# Guide\nRFCs live in `docs/rfcs/`; ADRs in docs/adr/. `[x](adr/a.md)`\n"
        )

        assert _broken_links(repo / "docs" / "guide.md", repo) == []

    def test_normal_links_are_unaffected(self, tmp_path: Path) -> None:
        repo = _make_tree(tmp_path, with_local_dirs=True)
        (repo / "docs" / "guide.md").write_text("# Guide\n[home](../README.md#title)\n")

        assert _broken_links(repo / "docs" / "guide.md", repo) == []

    def test_tracked_docs_in_this_repo_have_no_such_links(self) -> None:
        offenders = {
            str(p.relative_to(REPO)): _broken_links(p)
            for p in _doc_files()
            if any("local-only" in problem for problem in _broken_links(p))
        }
        assert offenders == {}
