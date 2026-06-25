---
step: 4
status: done
depends_on: [1]
files_modified: [pyproject.toml, carter/__init__.py, .gitignore, tests/test_version.py]
---

## Step 4: hatch-vcs dynamic version + drop static version (TDD)

### Tasks (red → green)
1. **RED** — add `tests/test_version.py`: assert
   `importlib.metadata.version("carter-ai")` is non-empty and PEP 440 valid; assert
   `carter.__version__` (if kept) equals it; parse pyproject and assert
   `dynamic = ["version"]` is set and NO static `[project].version` literal remains.
2. **GREEN** — pyproject.toml: set `[build-system] requires = ["hatchling",
   "hatch-vcs"]`; add `dynamic = ["version"]` to `[project]` and REMOVE
   `version = "2.0.0a1"`; add `[tool.hatch.version] source = "vcs"`. Either configure
   `[tool.hatch.build.hooks.vcs] version-file = "carter/_version.py"` and re-export
   in `carter/__init__.py` (`from carter._version import __version__`), OR drop
   `__version__` entirely and rely on `importlib.metadata`. Add `carter/_version.py`
   to `.gitignore`.
3. Verify `uv build` (or `hatch version`) reports a tag-derived version; with no tag
   yet it yields a dev version (e.g. `2.0.1.devN+g<sha>`) — expected until step 6.
4. Confirm `carter --version` (Click reads `importlib.metadata`) resolves with no error.

### Done criteria
- `tests/test_version.py` green; `[project].version` removed; `dynamic = ["version"]` set.
- `uv build` produces a wheel whose version comes from VCS.
- No SemVer literal anywhere in `carter/__init__.py`.

### Notes
Decouples version from source — the dual-source drift root cause. The REAL version
appears after step 6 tags `v2.0.0`. Keep `carter/_version.py` gitignored (build
artifact). Confirm the wheel's `*.dist-info/METADATA` Version field is VCS-derived.
