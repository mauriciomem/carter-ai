"""No file in the repository holds a token-shaped literal (plan 003 step 25).

GitHub push protection and secret scanning flag ``github_pat_`` / ``ghp_`` / ``gho_`` /
``ghu_`` / ``ghs_`` / ``ghr_`` followed by 20 or more token characters, even for made-up
values. Tests build such sentinels at runtime (``tests/sentinels.py``). The scanner below
is written with the prefixes split so that this file does not match itself.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from sentinels import fine_grained, prefixed

REPO = Path(__file__).resolve().parent.parent
MIN_TAIL = 20
PREFIXES = ("github" + "_pat_", *("gh" + c + "_" for c in "pousr"))
TOKEN_SHAPED = re.compile(
    "(?:" + "|".join(re.escape(p) for p in PREFIXES) + ")[A-Za-z0-9_]{" + str(MIN_TAIL) + ",}"
)
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".gif", ".ico", ".whl", ".zip", ".gz", ".bundle"}
MAX_BYTES = 4_000_000


def candidate_files() -> list[Path]:
    """Tracked and not-ignored untracked files; a directory walk if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=REPO,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
        files = [REPO / n for n in names]
    except (OSError, subprocess.SubprocessError):
        files = []
        for root, dirs, names in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]
            files += [Path(root) / n for n in names]
    return [
        f
        for f in files
        if f.is_file()
        and not f.is_symlink()
        and f.suffix not in SKIP_SUFFIXES
        and f.stat().st_size <= MAX_BYTES
    ]


def offenders() -> list[str]:
    found = []
    for path in candidate_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), start=1):
            if TOKEN_SHAPED.search(line):
                found.append(f"{path.relative_to(REPO)}:{number}")
    return found


def test_the_scanner_flags_a_runtime_built_sample_and_ignores_split_literals() -> None:
    assert TOKEN_SHAPED.search(fine_grained("X")) and TOKEN_SHAPED.search(prefixed("ghp_", "X"))
    assert not TOKEN_SHAPED.search('"github_pat_" + "11AAAA"')
    assert not TOKEN_SHAPED.search("github_pat_[A-Za-z0-9_]{22,}")  # a regex definition
    assert not TOKEN_SHAPED.search("ghp_S3cr3tLeak-012345678901234567890abcd")  # hyphen splits it


def test_the_sentinel_helpers_build_values_that_look_like_tokens() -> None:
    assert len(fine_grained()) > 60 and fine_grained("TAG").count("TAG") == 1
    assert len(prefixed("gho_")) == 40


def test_no_tracked_file_contains_a_token_shaped_literal() -> None:
    assert offenders() == []
