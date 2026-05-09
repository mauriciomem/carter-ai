# Testing Guide

This document covers the Carter test suite — what it tests, how to run it, how it works, and how to extend it when adding new features.

## Overview

The test suite validates the **installer** (`install.py`), which is the only executable code in the project. Everything else — agents, skills, MCP configs, knowledge templates — are static Markdown or JSON files that the installer copies to the right locations on disk.

The tests run in full isolation using temporary directories, so they never touch your real `~/.copilot/` or `~/.config/opencode/` paths.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (used to run tests without managing virtual environments)

No explicit `pip install` is required. The `uv run --with pytest` command handles the pytest dependency automatically.

## Running Tests

```bash
# Run all tests with verbose output
uv run --with pytest pytest tests/ -v

# Run a specific test class
uv run --with pytest pytest tests/test_install.py::TestMCPMerging -v

# Run a single test
uv run --with pytest pytest tests/test_install.py::TestIdempotency::test_second_run_unchanged -v

# Show print output (useful for debugging)
uv run --with pytest pytest tests/ -v -s
```

## Tools & Libraries

| Tool | Purpose |
|------|---------|
| [pytest](https://docs.pytest.org/) | Test runner and assertion library |
| `tmp_path` (pytest built-in) | Provides a unique temporary directory per test, cleaned up automatically |
| `pathlib.Path` | All file operations use `Path` objects (no `os.path`) |
| `json` (stdlib) | Used to create and verify JSON settings files |

No external mocking libraries are used. The installer accepts a `base_dir` parameter that redirects all file operations to a temp directory, making mocks unnecessary.

## Project Layout

```
tests/
├── conftest.py         # Shared fixtures
└── test_install.py     # All installer tests (20 tests, 8 classes)
```

## Fixtures (conftest.py)

Fixtures are reusable setup functions that pytest injects into tests by name. All fixtures live in `tests/conftest.py`.

| Fixture | Type | Description |
|---------|------|-------------|
| `repo_root` | `Path` | Absolute path to the Carter repository root. Used when tests need to reference source files. |
| `base_dir` | `Path` | A fresh `tmp_path` directory. Every installer function accepts this as a parameter, so all file writes go here instead of real user directories. |
| `copilot_dir` | `Path` | `base_dir/copilot/`, pre-created. Represents `~/.copilot/`. |
| `opencode_dir` | `Path` | `base_dir/opencode/`, pre-created. Represents `~/.config/opencode/`. |
| `vscode_settings` | `Path` | An empty `settings.json` at `base_dir/vscode/settings.json`. Simulates a fresh VS Code config. |
| `existing_settings` | `Path` | A `settings.json` pre-populated with `editor.fontSize` and a non-Carter MCP server. Simulates a user who already has VS Code configured. |

### How `base_dir` Isolation Works

The installer's functions (e.g., `install_agents`, `install_skills`) accept a `base_dir` argument. In production, this defaults to the user's home directory. In tests, it's always `tmp_path` — a unique temporary directory that pytest creates and cleans up per test. This means:

- Tests never read or write to `~/.copilot/`
- Every test starts with a clean filesystem
- Tests can run in parallel without conflicts

## Test Classes

### TestInstallAgents (4 tests)

Validates that agent Markdown files are correctly copied to target directories.

| Test | What It Verifies |
|------|-----------------|
| `test_creates_copilot_agents` | All 6 `carter-*.md` files are created under `base_dir/copilot/agents/` |
| `test_creates_opencode_agents` | Same 6 files under `base_dir/opencode/agents/` |
| `test_creates_both_targets` | Both targets installed simultaneously produce 6 files each |
| `test_manifest_tracks_files` | Every installed file is recorded in the manifest with a `sha256:` hash |

### TestInstallSkills (2 tests)

Validates that skill directories and their `SKILL.md` files are created.

| Test | What It Verifies |
|------|-----------------|
| `test_creates_copilot_skills` | 17 `carter-*` skill directories, each with a `SKILL.md`, under Copilot target |
| `test_creates_opencode_skills` | Same 17 directories under OpenCode target |

### TestInstallInstructions (1 test)

| Test | What It Verifies |
|------|-----------------|
| `test_creates_instructions` | `copilot-instructions.md` is created and contains "Carter" |

### TestInstallKnowledge (2 tests)

Validates the knowledge base template installation.

| Test | What It Verifies |
|------|-----------------|
| `test_creates_knowledge_files` | All 6 knowledge templates are created (decisions, mistakes, patterns, debugging, infrastructure, project-history) |
| `test_does_not_overwrite_existing` | If a user has edited a knowledge file, the installer preserves their content instead of overwriting |

### TestIdempotency (2 tests)

Validates that running the installer multiple times is safe.

| Test | What It Verifies |
|------|-----------------|
| `test_second_run_unchanged` | A second install reports all 6 agent files as `unchanged` (0 created, 0 updated) |
| `test_modified_file_detected_as_updated` | If a file is modified externally, the installer detects and reports it as `updated` |

### TestMCPMerging (3 tests)

Validates JSON merging logic for VS Code `settings.json`.

| Test | What It Verifies |
|------|-----------------|
| `test_merge_into_empty_settings` | Carter MCP servers are added to an empty `settings.json` |
| `test_preserves_existing_servers` | Existing non-Carter MCP servers survive the merge |
| `test_preserves_other_settings` | Non-MCP settings (e.g., `editor.fontSize`) are untouched |

### TestManifest (2 tests)

Validates the manifest file (`.carter-manifest.json`) used for tracking and uninstall.

| Test | What It Verifies |
|------|-----------------|
| `test_write_and_read_manifest` | Manifest round-trips correctly (write → read → identical data) |
| `test_read_nonexistent_manifest` | Reading a missing manifest returns `None` instead of crashing |

### TestUninstall (2 tests)

Validates clean removal of Carter files.

| Test | What It Verifies |
|------|-----------------|
| `test_uninstall_removes_carter_files` | All `carter-*` agent and skill files are removed |
| `test_uninstall_preserves_non_carter_files` | Non-Carter files in the same directories are not deleted |

### TestHashing (2 tests)

Validates the SHA-256 hashing utility used for change detection.

| Test | What It Verifies |
|------|-----------------|
| `test_sha256_consistent` | Same file produces the same hash on repeated calls; hash starts with `sha256:` |
| `test_sha256_different_content` | Different content produces different hashes |

## Extending the Test Suite

### When to Add Tests

Add tests when you:

- Add a new installer function (e.g., `install_themes()`)
- Add a new file type that gets installed (e.g., a new agent or skill)
- Change merge logic (e.g., adding OpenCode MCP support)
- Modify manifest structure
- Add new CLI flags

### How to Add a Test

**1. Decide which class it belongs to.** Group by feature. If none fit, create a new class with a section comment:

```python
# ──────────────────────────────────────────────────────────────────────────────
# Your Feature Name
# ──────────────────────────────────────────────────────────────────────────────

class TestYourFeature:
    ...
```

**2. Use `base_dir` for filesystem isolation.** Every test that touches files should use the `base_dir` fixture:

```python
def test_my_new_feature(self, base_dir: Path) -> None:
    manifest = {"files": [], "file_hashes": {}}
    backup = base_dir / "backup"

    # Call the installer function with base_dir
    install.my_new_function(["copilot"], base_dir, manifest, backup)

    # Assert the expected outcome
    output = base_dir / "copilot" / "my_feature" / "output.md"
    assert output.exists()
    assert "expected content" in output.read_text()
```

**3. For JSON/settings tests**, create the settings file in the test body or use the `vscode_settings` / `existing_settings` fixtures:

```python
def test_my_merge_logic(self, base_dir: Path) -> None:
    settings = base_dir / "vscode" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"existing.key": "value"}))

    install.my_merge_function(settings, new_data)

    result = json.loads(settings.read_text())
    assert result["existing.key"] == "value"  # preserved
    assert "new.key" in result                  # added
```

**4. Test idempotency for any new install function.** Run it twice and verify the second run reports no changes:

```python
def test_idempotent(self, base_dir: Path) -> None:
    manifest = {"files": [], "file_hashes": {}}
    backup = base_dir / "backup"

    install.my_function(["copilot"], base_dir, manifest, backup)

    manifest2 = {"files": [], "file_hashes": {}}
    stats = install.my_function(["copilot"], base_dir, manifest2, backup)

    assert stats["unchanged"] > 0
    assert stats["created"] == 0
```

**5. Test uninstall for any new file type.** Verify Carter files are removed and non-Carter files survive.

### Adding a New Fixture

If multiple tests need the same setup, add a fixture to `conftest.py`:

```python
@pytest.fixture
def my_fixture(base_dir: Path) -> Path:
    """Describe what this sets up."""
    d = base_dir / "some" / "path"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

Fixtures can depend on other fixtures (like `base_dir` above). Pytest resolves the dependency graph automatically.

## Common Patterns

### Verifying file counts

```python
actual = sorted(f.name for f in some_dir.glob("carter-*.md"))
assert len(actual) == 6
```

### Verifying file content

```python
content = some_file.read_text()
assert "expected string" in content
```

### Verifying non-destructive behavior

```python
# Pre-create a file with custom content
existing.write_text("custom content\n")

# Run installer
install.some_function(...)

# Verify it wasn't overwritten
assert existing.read_text() == "custom content\n"
```

### Verifying JSON merging

```python
data = json.loads(settings.read_text())
assert "new-key" in data["mcp.servers"]     # added
assert "old-key" in data["mcp.servers"]     # preserved
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'install'`

The test file adds the repo root to `sys.path` at import time. Make sure you're running pytest from the repository root:

```bash
cd ~/carter-ai
uv run --with pytest pytest tests/ -v
```

### Tests pass locally but fail in CI

Check that the CI runner has `uv` and Python 3.11+ installed. See the GitHub Actions workflow in `.github/workflows/` if available.

### A test is failing after adding a new agent/skill

If you added a new file (e.g., a 7th agent), update the expected counts in the relevant test assertions. Search for the current count (e.g., `== 6`) and update it.
