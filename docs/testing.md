# Testing Guide

This document covers the Carter test suite — what it tests, how to run it, how it works, and how to extend it when adding new features.

## Overview

The test suite validates these systems:

| System | Test File | What It Covers |
|--------|-----------|----------------|
| **Installer** | `tests/test_install.py` | File copying, MCP merging, manifest tracking, idempotency |
| **Scaffold (CLI + Templates)** | `tests/test_scaffold.py` | Config loading, template rendering, quality gates, **policy emission**, workspace init |
| **Policy model** | `tests/test_config.py` | The `policy` block, risk taxonomy, per-agent allowlist, gate precedence, overrides |
| **Policy lint** | `tests/test_policy_lint.py` | `carter check` drift detection, hard ack, redaction WARN |
| **Agent parity** | `tests/test_parity.py` | Static↔template invariants, baked policy frontmatter, no false claims |
| **Plans & state** | `tests/test_plans.py`, `tests/test_state.py` | Plan frontmatter contract, checkpoint recovery, `.carter/` git state |
| **Carter-Ops** | `tests/ops/test_operations.py` | CLI parsing, operations, the policy-override ledger, attribution |

The tests run in full isolation using temporary directories — they never touch your real `~/.copilot/`, `~/.config/opencode/`, or any workspace paths.

## Prerequisites

All three suites import from the installed `carter` package (Click, Jinja2,
PyYAML, httpx), so the simplest setup is a venv with the package installed in
editable mode:

```bash
# Create and activate a venv with the package installed
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

> **Troubleshooting — `carter` CLI crashes with `ModuleNotFoundError: No module
> named 'carter.cli'`.** This affects the **editable dev install only** (a shipped
> `uv tool install` wheel is unaffected). The wheel bundles static content under
> `carter/_data/` via `force-include` (see `pyproject.toml`); in an editable
> install that materializes `carter/_data` as a real directory in `site-packages`,
> which **shadows** the `.pth` redirect to your source — `import carter` then finds
> the stub (only `_data`, no `cli`). Running `pytest` from the repo root can
> re-trigger it. Fix by symlinking the source package over the shadow:
>
> ```bash
> SP=.venv/lib/python3.13/site-packages   # adjust the python3.13 for your version
> rm -rf "$SP/carter" && ln -s "$PWD/carter" "$SP/carter"
> carter --version                        # verify
> ```
>
> The symlink survives the editable-rebuild trigger. `carter/resources.py`
> `data_dir()` still resolves bundled content from the repo root in a checkout.

### Run everything

```bash
# From the venv (covers every test file — 467 tests)
python -m pytest tests/ -v
```

### Run a single suite

```bash
python -m pytest tests/test_install.py -v     # installer (75)
python -m pytest tests/test_scaffold.py -v    # scaffold + policy emission (154)
python -m pytest tests/test_config.py -v      # policy model (24)
python -m pytest tests/test_policy_lint.py -v # policy lint / carter check (26)
python -m pytest tests/test_parity.py -v      # agent source parity (17)
python -m pytest tests/test_plans.py -v       # plan frontmatter contract (80)
python -m pytest tests/ops/ -v                # carter-ops (78)
```

## Continuous Integration

CI runs as **two tiers** (ADR-0009 D5): a free, deterministic, key-free gate on
every PR, and a budgeted live-accuracy canary on a weekly cron.

| Tier | Workflow | Trigger | Key? | What it proves |
|------|----------|---------|------|----------------|
| **PR gate** (required) | [ci.yml](../.github/workflows/ci.yml) | every push to `main` + every PR | none | Functionality + structural accuracy: `ruff check`, `ruff format --check`, `mypy`, unit tests + offline evals (py3.11 & py3.13), and a real `install-smoke` (`uv tool install` → `carter --version`/`init`/`check`) on Linux + macOS |
| **Live canary** (informational) | [evals-live.yml](../.github/workflows/evals-live.yml) | weekly cron + manual dispatch | one repo secret | Prompt-quality accuracy + token/latency/cost against a budgeted low-cost model |

The PR gate, in full:

```bash
uv venv --clear
uv pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy        # lint + types
python -m pytest tests/ -q                                  # 467 unit tests
python -m pytest evals/test_skills.py evals/test_routing.py evals/test_metrics.py -q  # offline evals
```

### Why the live evals need an API key (and the PR gate does not)

The live evals (`evals/test_live.py`, marked `live`) send the agent/skill prompt
markdown to a **raw model** and assert on the response. Locally they reuse your
GitHub Copilot OAuth token (via OpenCode's `auth.json` or `gh auth token`), so no
extra key is needed. **CI runners cannot do this:** there is no Copilot OAuth token
on a runner — `gh auth token` there yields only the repo `GITHUB_TOKEN`, which the
Copilot API rejects, and there is no `opencode/auth.json`. Running live evals in CI
therefore *requires* a dedicated LLM key.

We do **not** want a key on the PR gate: it would cost money per PR, be
non-deterministic (a flaky merge gate), and expose a secret to fork PRs. So:

- **PR gate stays key-free** — offline evals assert on prompt *structure* only.
- **The weekly canary** (`evals-live.yml`) supplies a single trusted
  `ANTHROPIC_API_KEY` **repo secret**, runs a Haiku-class model with a hard
  `EVAL_MAX_TOKENS` cap, and uploads an `eval-metrics` artifact (pass count, total
  tokens, mean latency, estimated USD — from `evals/metrics.py:summary()`). If the
  secret is unset the live tests skip cleanly. **A key is never committed; it lives
  only in repo secrets.**

> **Read the canary honestly:** it measures the prompt sent to a raw model — a proxy
> for *prompt quality*, **not** the real VS Code Copilot tool-calling loop. Treat it
> as an accuracy/cost trend, not a pass/fail merge signal.

The agent-generation drift check described in
[ADR-0002](adr/0002-single-source-agent-generation.md) is deferred until the
static/template sources are reconciled; until then, `tests/test_parity.py` is the
drift guardrail.

## Tools & Libraries

| Tool | Purpose |
|------|---------|
| [pytest](https://docs.pytest.org/) | Test runner and assertion library |
| `tmp_path` (pytest built-in) | Provides a unique temporary directory per test, cleaned up automatically |
| `pathlib.Path` | All file operations use `Path` objects (no `os.path`) |
| `json` (stdlib) | Used to create and verify JSON settings files |
| [Jinja2](https://jinja.palletsprojects.com/) | Template engine (scaffold tests exercise template rendering) |
| [PyYAML](https://pyyaml.org/) | YAML config parsing (scaffold tests exercise config loading) |

No external mocking libraries are used. Both the installer and the scaffold accept path parameters that redirect file operations to temp directories.

## Project Layout

```
tests/
├── conftest.py             # Shared fixtures (base_dir, settings, etc.)
├── test_install.py         # Installer tests (75)
├── test_scaffold.py        # Scaffold + policy emission tests (154)
├── test_config.py          # Policy model: taxonomy, allowlist, overrides (24)
├── test_policy_lint.py     # carter check policy lint + hard ack (26)
├── test_parity.py          # Agent source-parity + baked policy frontmatter (17)
├── test_plans.py           # Plan frontmatter contract + recovery (80)
├── test_state.py           # .carter/ git state (13)
└── ops/
    ├── conftest.py         # Ops path setup
    └── test_operations.py  # Carter-ops + policy-override ledger (78)
```

The full suite is **467 tests** (`python -m pytest tests/ -v`), plus 28 offline
evals under `evals/`.

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

## Test organization

Tests are grouped into classes by behavior within each file (see
[Project Layout](#project-layout)). Rather than enumerate every class here — which
goes stale the moment a test is added — discover them from the source:

```bash
python -m pytest tests/ --co -q          # list every test (collection only)
python -m pytest tests/test_config.py -v # one suite, with class/test names
```

Each class name states what it covers (e.g. `TestPolicyOverridesAreHonored`,
`TestLintNativeKeyDrift`, `TestStrictnessPolicyParity`), and every test name
describes the behavior it asserts.

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


class TestYourFeature: ...
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
    assert "new.key" in result  # added
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
assert "new-key" in data["mcp.servers"]  # added
assert "old-key" in data["mcp.servers"]  # preserved
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

### Ops tests fail with `ModuleNotFoundError`

The ops tests manipulate `sys.path` to import from `ops/`. Make sure you're running from the repo root and that `tests/ops/conftest.py` exists (it adds the path).
