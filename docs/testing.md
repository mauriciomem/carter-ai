# Testing Guide

This document covers the Carter test suite — what it tests, how to run it, how it works, and how to extend it when adding new features.

## Overview

The test suite validates these systems:

| System | Test File | What It Covers |
|--------|-----------|----------------|
| **Installer** | `tests/test_install.py`, `tests/test_install_opencode.py` | File copying, OpenCode >= 2.1 gate, V2 `mcp.servers` merging, manifest tracking, idempotency |
| **Harness check** | `tests/test_harness.py` | `carter check` running `opencode debug agents` (faked) |
| **Scaffold (CLI + Templates)** | `tests/test_scaffold.py` | Config loading, template rendering, quality gates, **policy emission**, workspace init |
| **Policy model** | `tests/test_config.py` | The `policy` block, risk taxonomy, per-agent allowlist, overrides, `permissions:` rule order |
| **Policy lint** | `tests/test_policy_lint.py` | `carter check` drift detection on emitted `permissions:`/`model`, V1-key rejection |
| **Models** | `tests/test_models.py` | Per-agent model resolution and emission |
| **Dispatch** | `tests/test_dispatch.py` | Native subagent dispatch emission |
| **Agent parity** | `tests/test_parity.py` | Rendered-template invariants, emitted frontmatter, no false claims |
| **Plans & state** | `tests/test_plans.py`, `tests/test_state.py` | Plan frontmatter contract, checkpoint recovery, `.carter/` git state |
| **Carter-Ops** | `tests/ops/test_operations.py` | `carter ops` audit, policy-override ledger, config emit |
| **Uninstall** | `tests/test_uninstall.py` | `carter uninstall` never deletes user-edited or user-owned files |
| **`ops:` routing** | `tests/test_ops_routing.py` | Local `ops:` steps run anywhere; remote steps only via carter-devops |
| **Skill hygiene** | `tests/test_skill_hygiene.py` | Skill sources carry only what OpenCode V2 reads |
| **Docs links** | `tests/test_docs_links.py` | Relative links and anchors in `README.md` and `docs/**` resolve |
| **Version** | `tests/test_version.py` | `carter.__version__` derives from package metadata |

The tests run in full isolation using temporary directories — they never touch your real `~/.carter/`, `~/.config/opencode/`, or any workspace paths. No test needs a real `opencode` binary: an autouse fixture
(`_no_real_opencode`) hides it, and tests that exercise the harness step use the
`fake_opencode` fixture instead.

At the time of writing the suite has **686 unit tests** and **59 offline evals**
(`uv run pytest --co -q` prints the current count). The evals have their own guide:
[evals/README.md](../evals/README.md).

## Prerequisites

The suites import the `carter` package, so set up the project environment with uv
(this also installs the dev tools: pytest, ruff, mypy, httpx for live evals):

```bash
uv sync --extra dev
```

> **Troubleshooting — `carter` CLI crashes with `ModuleNotFoundError: No module
> named 'carter.cli'`.** This affects the **editable dev install only** (a shipped
> `uv tool install` wheel is unaffected). The wheel bundles static content under
> `carter/_data/` via `force-include` (see `pyproject.toml`); in an editable
> install that materializes `carter/_data` as a real directory in `site-packages`,
> which **shadows** the `.pth` redirect to your source — `import carter` then finds
> the stub (only `_data`, no `cli`). Fix by symlinking the source package over the
> shadow (replace `python3.X` with your version and delete the shadow directory
> first):
>
> ```bash
> SP=.venv/lib/python3.X/site-packages
> ln -sfn "$PWD/carter" "$SP/carter"      # after removing the shadow "$SP/carter" dir
> uv run carter --version                 # verify
> ```

### Run everything

```bash
uv run pytest -q                       # unit tests (tests/, via pyproject testpaths)
uv run pytest evals -m "not live" -q   # offline evals
```

### Run a single suite

```bash
uv run pytest tests/test_install.py -v
uv run pytest tests/ops/ -v
```

## Continuous Integration

CI runs as **two tiers**: a free, deterministic, key-free gate on
every PR, and a budgeted live-accuracy canary on a weekly cron.

| Tier | Workflow | Trigger | Key? | What it proves |
|------|----------|---------|------|----------------|
| **PR gate** (required) | [ci.yml](../.github/workflows/ci.yml) | every push to `main` + every PR | none | Functionality + structural accuracy: `ruff check`, `ruff format --check`, `mypy`, unit tests + offline evals (py3.11, 3.14 & 3.15), and a real `install-smoke` (`uv tool install` → `carter --version`/`init`/`check`/`install`) on Linux + macOS |
| **Live canary** (informational) | [evals-live.yml](../.github/workflows/evals-live.yml) | weekly cron + manual dispatch | one repo secret | Prompt-quality accuracy + token/latency/cost against a budgeted low-cost model |

The PR gate, in full:

```bash
uv sync --locked --extra dev
uv run ruff check . && uv run ruff format --check . && uv run mypy   # lint + types
uv run pytest tests/ -q                                             # unit tests
uv run pytest evals/ -m "not live" -q                               # offline evals
```

### install-smoke matrix

The `install-smoke` job in [ci.yml](../.github/workflows/ci.yml) installs Carter as a
real `uv tool` and runs it against a real OpenCode:

| Axis | Values |
|------|--------|
| OS | Linux (`ubuntu-latest`) and macOS (`macos-latest`) |
| OpenCode `floor` | `2.1.0`, the minimum supported version — **required** to pass |
| OpenCode `latest` | newest published 2.x — **informational** (allowed to fail, so upstream changes don't block PRs) |

Each cell checks that `carter --version` is a valid PEP 440 version, runs
`carter init` + `carter check` on a fresh workspace, and runs `carter install` into a
throwaway home, asserting that at least 8 agent files land in the OpenCode agents
directory.

#### Bumping the OpenCode floor

1. Change `MIN_OPENCODE` in [`carter/install/prereqs.py`](../carter/install/prereqs.py).
2. Change the `floor` entry's `opencode:` version in
   [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) in the **same** commit.
3. Update user-facing "2.1" wording (`README.md`, `docs/`, the `carter install` help
   text and the "OpenCode >= 2.1" test names/messages) — `grep -rn "2\.1" README.md docs carter tests`.

### Why the live evals need an API key (and the PR gate does not)

The live evals are every test marked `live`: the prompt-quality canary
(`evals/test_live.py`, which sends agent/skill prompt markdown to a **raw model** and
asserts on the response) and the live adherence run (`evals/test_adherence_live.py`).
Run them with `uv run pytest evals/ -m live -v`. They read a standard
provider key from your environment — `ANTHROPIC_API_KEY`, else `OPENAI_API_KEY` — and
skip cleanly when neither is set. They never read stored OpenCode or `gh` credentials,
so running live evals in CI *requires* a dedicated LLM key.

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
> for *prompt quality*, **not** the real OpenCode tool-calling loop. Treat it
> as an accuracy/cost trend, not a pass/fail merge signal.

Agents have one source (`templates/`); `tests/test_parity.py` guards what the
rendered files claim and emit.

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
├── conftest.py             # Shared fixtures (repo_root, base_dir, fake_opencode, _no_real_opencode)
├── test_install.py         # Installer
├── test_install_opencode.py # OpenCode >= 2.1 gate, V2 MCP shape
├── test_harness.py         # opencode debug agents validation
├── test_scaffold.py        # Scaffold + policy emission
├── test_config.py          # Policy model: taxonomy, allowlist, overrides
├── test_policy_lint.py     # carter check policy lint
├── test_models.py          # Per-agent model resolution
├── test_dispatch.py        # Native subagent dispatch
├── test_parity.py          # Rendered agent invariants
├── test_plans.py           # Plan frontmatter contract + recovery
├── test_state.py           # .carter/ git state
├── test_uninstall.py       # uninstall keeps user-edited files
├── test_ops_routing.py     # ops: local vs remote (devops-only) steps
├── test_skill_hygiene.py   # skill frontmatter hygiene
├── test_docs_links.py      # README/docs relative links resolve
├── test_version.py         # Version metadata
└── ops/
    └── test_operations.py  # carter ops: audit, policy-override, config
```

## Fixtures (conftest.py)

Shared fixtures live in `tests/conftest.py`; suites define local fixtures where only they need them.

| Fixture | Type | Description |
|---------|------|-------------|
| `repo_root` | `Path` | Absolute path to the Carter repository root. Used when tests need to reference source files. |
| `base_dir` | `Path` | A fresh `tmp_path` directory. Every installer function accepts this as a parameter, so all file writes go here instead of real user directories. |
| `fake_opencode` | factory | Puts a fake `opencode` on an isolated `PATH`. Call it with the `--version` output (or `None` for "not installed") and optionally the `debug agents` output and exit code, or `agents_sequence` (one output per call) to simulate stale-then-fresh service answers. |
| `_no_real_opencode` | autouse | Stops `carter check` from running a developer's real `opencode`; skipped for tests that request `fake_opencode`. |

### How `base_dir` Isolation Works

The installer's functions (e.g., `install_agents`, `install_skills`) accept a `base_dir` argument. In production, this defaults to the user's home directory. In tests, it's always `tmp_path` — a unique temporary directory that pytest creates and cleans up per test. This means:

- Tests never read or write to your real home directory
- Every test starts with a clean filesystem
- Tests can run in parallel without conflicts

## Test organization

Tests are grouped into classes by behavior within each file (see
[Project Layout](#project-layout)). Rather than enumerate every class here — which
goes stale the moment a test is added — discover them from the source:

```bash
uv run pytest tests/ --co -q          # list every test (collection only)
uv run pytest tests/test_config.py -v # one suite, with class/test names
```

Each class name states what it covers (e.g. `TestPolicyOverridesAreHonored`,
`TestLintNativeKeyDrift`, `TestStrictnessPolicyParity`), and every test name
describes the behavior it asserts.

## Extending the Test Suite

### When to Add Tests

Add tests when you:

- Add a new installer function (e.g., `install_themes()`)
- Add a new file type that gets installed (e.g., a new agent or skill)
- Change merge logic (e.g., the `mcp.servers` merge)
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
    install.my_new_function(base_dir, manifest, backup)

    # Assert the expected outcome
    output = base_dir / "opencode" / "my_feature" / "output.md"
    assert output.exists()
    assert "expected content" in output.read_text()
```

**3. For JSON/settings tests**, create the settings file in the test body:

```python
def test_my_merge_logic(self, base_dir: Path) -> None:
    settings = base_dir / "opencode" / "opencode.json"
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

    install.my_function(base_dir, manifest, backup)

    manifest2 = {"files": [], "file_hashes": {}}
    stats = install.my_function(base_dir, manifest2, backup)

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
assert len(actual) == 8
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
assert "new-key" in data["mcp"]["servers"]  # added
assert "old-key" in data["mcp"]["servers"]  # preserved
```

## Troubleshooting

### Tests pass locally but fail in CI

CI runs `uv sync --locked`, so a dependency change must be reflected in `uv.lock`
(`uv lock`). See [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

### A test is failing after adding a new agent/skill

Some tests assert exact agent/skill sets. Search the tests for the current list and add the new entry.
