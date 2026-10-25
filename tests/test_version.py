"""Version is single-sourced from VCS via hatch-vcs.

No SemVer literal lives in source: ``[project].version`` is dropped in favour of
``dynamic = ["version"]`` and ``carter.__version__`` derives from package metadata.
"""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import carter

# PEP 440 release/pre/post/dev/local segments (simplified but covers what hatch-vcs emits).
_PEP440 = re.compile(
    r"^([1-9][0-9]*!)?"
    r"(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*"
    r"((a|b|rc)(0|[1-9][0-9]*))?"
    r"(\.post(0|[1-9][0-9]*))?"
    r"(\.dev(0|[1-9][0-9]*))?"
    r"(\+[a-z0-9]+(\.[a-z0-9]+)*)?$",
    re.IGNORECASE,
)

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_installed_version_is_valid_pep440():
    v = version("carter-ai")
    assert v, "carter-ai reports an empty version"
    assert _PEP440.match(v), f"version is not PEP 440 valid: {v!r}"


def test_dunder_version_matches_metadata():
    assert carter.__version__ == version("carter-ai")


def test_no_semver_literal_in_init():
    init_src = (Path(carter.__file__).parent / "__init__.py").read_text()
    # Flag a SemVer release literal (X.Y[.Z]); the "0+unknown" PackageNotFound
    # sentinel is not a release string and is allowed.
    assert not re.search(r"__version__\s*=\s*['\"]\d+\.\d+", init_src), (
        "a hard-coded SemVer __version__ literal must not remain in carter/__init__.py"
    )


def test_pyproject_version_is_dynamic():
    data = tomllib.loads(PYPROJECT.read_text())
    project = data["project"]
    assert "version" not in project, "static [project].version must be removed (tag-driven)"
    assert "version" in project.get("dynamic", []), 'dynamic must include "version"'
