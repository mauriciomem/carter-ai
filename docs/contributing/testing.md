# Testing

How to run Carter's tests, what CI checks, and how to add tests. The prompt and skill
evals have their own guide: [evals/README.md](../../evals/README.md).

## Run the tests

```bash
uv sync --extra dev                     # once
uv run pytest -q                        # unit tests (tests/)
uv run pytest evals -m "not live" -q    # offline evals
uv run pytest tests/test_install.py -v  # one file
uv run pytest --co -q                   # list tests without running them
```

The tests are fully isolated. They write only to temporary directories and never
touch your `~/.carter/`, `~/.config/opencode/` or workspaces. No test needs a real
`opencode`: a fixture hides it, and tests that exercise `carter check` use a fake one.

## What the suites cover

| Area | Files |
|------|-------|
| Installer, OpenCode version check, MCP config | `test_install.py`, `test_install_opencode.py` |
| Uninstall keeps user files | `test_uninstall.py` |
| Templates, workspace init, permission output | `test_scaffold.py` |
| Safety policy model and overrides | `test_config.py` |
| `carter check` drift detection | `test_policy_lint.py` |
| `carter check` against OpenCode (faked) | `test_harness.py` |
| Models per agent | `test_models.py` |
| Subagent dispatch | `test_dispatch.py` |
| What rendered agents claim and emit | `test_parity.py` |
| Plans, checkpoints, `.carter/` state | `test_plans.py`, `test_state.py` |
| `carter ops` | `ops/test_operations.py` |
| `ops:` routing (remote steps only via DevOps) | `test_ops_routing.py` |
| Skill files | `test_skill_hygiene.py` |
| Links and anchors in `README.md` and `docs/` | `test_docs_links.py` |
| Version metadata | `test_version.py` |

Tests are grouped into classes named after the behavior they cover, for example
`TestPolicyOverridesAreHonored`.

## Continuous integration

| Workflow | When | Needs a key | Checks |
|----------|------|-------------|--------|
| [`ci.yml`](../../.github/workflows/ci.yml) | Every push to `main` and every PR | No | ruff, mypy, unit tests and offline evals on Python 3.11, 3.14 and 3.15, and an install smoke test |
| [`evals-live.yml`](../../.github/workflows/evals-live.yml) | Mondays 06:00 UTC, or manually | Yes (repo secret) | Live evals against a low-cost model, with token and cost metrics |
| [`release.yml`](../../.github/workflows/release.yml) | Every push to `main` | No | Tags and publishes a release ([details](development.md#releases)) |

CI installs dependencies with `uv sync --locked`, so update `uv.lock` (`uv lock`)
when you change dependencies.

### Install smoke test

The `install-smoke` job installs Carter as a real uv tool on Linux and macOS and runs
it against a real OpenCode:

- **floor** (`2.1.0`, the minimum supported version) must pass;
- **latest** (newest 2.x) is informational and may fail without blocking the PR.

Each run checks that `carter --version` is a valid version, runs `carter init` and
`carter check` on a fresh workspace, and runs `carter install` into a throwaway home,
expecting at least 8 agent files.

### Why the PR gate has no API key

A model call on every PR would cost money, give flaky results and expose a secret to
pull requests from forks. So the PR gate checks prompt **structure** only. The weekly
live run uses a single repository secret, a capped token budget and a cheap model.
It sends prompts to the raw model, not through OpenCode's full tool loop, so treat
it as a trend, not a merge gate.

## Add a test

Add tests when you add an installer step, a new installed file type, a CLI option,
or change MCP merging or the manifest.

1. Put it in the class for that feature, or create a new class.
2. Use the `base_dir` fixture, a fresh temporary directory that every installer
   function accepts, so nothing touches your home directory.
3. For new install steps, also test that running twice changes nothing and that
   uninstall removes Carter's files but keeps the user's.

```python
def test_keeps_user_file(self, base_dir: Path) -> None:
    existing = base_dir / "carter" / "knowledge" / "patterns.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("custom content\n")

    install_knowledge(base_dir, {"files": [], "file_hashes": {}}, base_dir / "backup")

    assert existing.read_text() == "custom content\n"
```

### Shared fixtures (`tests/conftest.py`)

| Fixture | Purpose |
|---------|---------|
| `repo_root` | Path to the repository root |
| `base_dir` | Fresh temporary directory for installer output |
| `fake_opencode` | Puts a fake `opencode` on `PATH` with chosen `--version` and `debug agents` output |
| `_no_real_opencode` | Automatic: keeps tests from calling your real `opencode` |

## When a test fails

- **Passes locally, fails in CI:** check that `uv.lock` is up to date.
- **Fails after adding an agent or skill:** some tests assert the exact set. Search
  the tests for the current list and add the new entry.
- **`test_docs_links.py` fails:** a relative link or `#anchor` in `README.md` or
  `docs/` points nowhere. The message names the file and target.
