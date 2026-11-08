# Development

How to work on Carter itself: set up a checkout, find your way around the
repository, and understand how releases happen.

## Set up

```bash
git clone https://github.com/mauriciomem/carter-ai.git
cd carter-ai
uv sync --extra dev        # project + pytest, ruff, mypy, httpx
uv run carter --version    # run the CLI from your checkout
```

Before you push, run what CI runs:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest -q
uv run pytest evals -m "not live" -q
```

See [Testing](testing.md) for details.

If imports look stale after switching branches, run `uv sync --reinstall`.

## Repository layout

```text
carter/          the CLI package
  cli.py           command definitions
  config.py        carter.yaml loading, models, permission rules
  scaffold.py      template rendering, permission lint
  harness.py       the `opencode debug agents` check
  plans.py         plan and checkpoint validation
  state.py         .carter/ workspace state
  install/         carter install / uninstall, MCP config
  ops/             carter ops (audit log, config)
  broker/          B: the push broker behind carter_push (plan 007)
  broker_cli.py    `python -I -m carter.broker_cli`, the only entry of the broker
templates/       Jinja2 templates for agents and AGENTS.md
skills/          skill definitions (edited by hand)
knowledge/       global knowledge seed files
mcp/opencode/    MCP server definitions
docs/            user documentation
tests/           unit tests (offline)
evals/           prompt and skill evals (offline and live)
```

The wheel bundles `skills/`, `knowledge/`, `mcp/` and `templates/` inside the
package, so `uv tool install` works without a checkout.

Agents have a single source, `templates/`: both `carter install` and `carter init`
render from it. To change what an agent says or may do, edit the template or
`carter/config.py`, never a generated file.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) in English
(`feat:`, `fix:`, `docs:`, …). The commit type decides the next version.

## Releases

Releases are automatic. On every push to `main`,
[`release.yml`](../../.github/workflows/release.yml) reads the commits since the last
tag, picks the next version, tags it, updates `CHANGELOG.md` and publishes a GitHub
Release.

| Commit type | Example | Version change |
|-------------|---------|----------------|
| `fix:` | `fix: handle a missing config file` | patch: `0.16.0 → 0.16.1` |
| `feat:` | `feat: add a terraform MCP option` | minor: `0.16.1 → 0.17.0` |
| `feat!:` or `BREAKING CHANGE:` | `feat!: drop python 3.10` | minor while below 1.0 |
| `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`, `style:` | `docs: fix a typo` | no release |

The Git tag is the only source of the version: `carter --version` and the wheel read
it through `hatch-vcs`. A checkout that isn't on a tag reports a development version
such as `0.16.1.dev3+g<sha>`. The project stays below 1.0 until the CLI and
configuration are stable.

## Raising the minimum OpenCode version

1. Change `MIN_OPENCODE` in [`carter/install/prereqs.py`](../../carter/install/prereqs.py).
2. Change the `floor` version in [`ci.yml`](../../.github/workflows/ci.yml) in the
   same commit.
3. Update the "2.1" wording in the docs, the `carter install` help text and the
   tests: `grep -rn "2\.1" README.md docs carter tests`.
