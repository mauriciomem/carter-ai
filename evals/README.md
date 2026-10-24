# Carter Eval Framework

A testing framework for evaluating the effectiveness and accuracy of Carter agents and skills.

## Overview

The eval framework operates in two modes:

| Mode | What it tests | Speed | Cost | CI-safe |
|------|--------------|-------|------|---------|
| **Offline** | Structural correctness of prompts, routing tables, skill patterns | Fast (~1s) | Free | Yes |
| **Live** | Actual model behavior when given agent/skill prompts | Slow (~30s per scenario) | API costs | Periodic only |

## Quick Start

```bash
uv sync --extra dev   # once: pytest, pyyaml, httpx

# Run offline evals (fast, no auth needed)
uv run pytest evals -m "not live" -v

# Run live evals only (uses your existing Copilot auth automatically)
uv run pytest evals -m live -v

# Run only routing / skill correctness evals
uv run pytest evals/test_routing.py -v
uv run pytest evals/test_skills.py -v

# Override model for live evals
EVAL_MODEL=gpt-4o uv run pytest evals/test_live.py -v
```

Pass the `evals` path: `evals/pytest.ini` registers the `live` marker, and the
repo-root config only collects `tests/`.

## Authentication

Live evals need an LLM. Authentication is resolved automatically in this order:

1. **GitHub Copilot** (preferred) — uses your existing `opencode` or `gh` CLI auth. No extra setup needed.
2. **ANTHROPIC_API_KEY** — env var with an Anthropic key
3. **OPENAI_API_KEY** — env var with an OpenAI key

If you're already using Copilot CLI or OpenCode, live evals work out of the box.

## Architecture

```
evals/
├── conftest.py            # Shared fixtures (repo paths, scenario loading)
├── pytest.ini             # Pytest config (live marker)
├── adherence.py           # Adherence grader (deterministic, no model call)
├── metrics.py             # Token/latency/cost normalization + run summary
├── test_routing.py        # Offline: routing table completeness & accuracy
├── test_skills.py         # Offline: skill content correctness
├── test_metrics.py        # Offline: metrics normalization
├── test_adherence.py      # Offline: replay the recorded adherence fixtures
├── test_live.py           # Live: actual model behavior evaluation
├── test_adherence_live.py # Live: Sonnet vs a thinker plan, graded against the bar
├── fixtures/              # Recorded Sonnet 4.6 runs (offline replay)
│   ├── implementer_adherence_sonnet.json
│   ├── narrator_adherence_sonnet.json
│   └── pm_adherence_sonnet.json
└── scenarios/
    ├── routing.yaml                  # Routing dispatch scenarios
    ├── carter_ops.yaml               # Carter-ops workflow scenarios
    ├── skills.yaml                   # Skill correctness scenarios
    ├── implementer_adherence.yaml    # Thinker plan + must_haves (engineer)
    ├── narrator_adherence.yaml       # Narrator downgrade gate
    └── pm_adherence.yaml             # PM downgrade gate
```

### Adherence eval (ADR-0010 D9)

The reliability backstop for the cheap-tier (Sonnet) implementer default; narrator
and pm have the same gate. The recorded fixtures are Sonnet 4.6 transcripts. It runs
the implementer against a **thinker-produced plan** carrying real `must_haves` (named
file paths, acceptance checks, step-level instructions) and grades adherence: the
fraction of `must_haves` satisfied + whether any **critical** step (a named-file touch,
an acceptance check, or a load-bearing intent) was missed.

**Pass-bar: ≥ 90% of `must_haves` satisfied AND 0 critical-step failures.** Below the
bar is a regression in *either* the model tier *or* the doc quality — and the
documentation-quality contract is fixed: choosing the cheaper model does **not** license
relaxing doc accuracy/detail (the plan stays at the Opus bar regardless of executor).

- **Per-PR (offline, free):** `test_adherence.py` replays the recorded transcripts in
  `fixtures/` and grades them deterministically — no
  API call. Runs in the `ci.yml` offline-eval step (`-m "not live"`).
- **Nightly/manual (billed):** `test_adherence_live.py` (carries the `live` marker)
  sends the plan to the live model (`EVAL_MODEL`) and grades the real transcript. Runs only on
  the `evals-live` cron / `workflow_dispatch` — **never** on the per-PR gate.
- **Re-record the fixture:** run the live test with `EVAL_RECORD=1` to overwrite the
  fixture with the fresh transcript + grade.

## What Each Test Layer Covers

### Offline: Routing (`test_routing.py`)

Tests the structural integrity of the routing system:

- **Table completeness** — Every agent file has a route in carter-maestro
- **No ambiguous triggers** — No keyword maps to multiple agents
- **Scenario coverage** — All routing scenarios match actual routing table entries
- **ops: trigger** — Every agent has the `ops:` one-liner

### Offline: Skills (`test_skills.py`)

Tests that skill files contain the correct instructional content:

- **Workflow phases** — Carter-ops teaches ASSESS→PLAN→APPROVE→EXECUTE→AUDIT→REPORT in order
- **Attribution flags** — Correct `--author` and `-S` git flags
- **No anti-patterns** — Skills don't teach legacy/deprecated approaches
- **Structural requirements** — All skills have frontmatter, adequate content
- **Domain coverage** — Each skill covers its core patterns (Terraform has resources, Go has error handling, etc.)

### Live: Model Behavior (`test_live.py`)

Tests actual model responses when given agent/skill prompts:

- **Carter-ops workflow** — Does the model show a plan, ask approval, include audit?
- **Approval gate** — Does the model refuse to auto-execute destructive operations?
- **Routing accuracy** — Does maestro dispatch to the correct agent?
- **Skill adherence** — Does the model follow skill-taught patterns?

## Scenarios

Scenarios are YAML files in `evals/scenarios/`. Each scenario has:

```yaml
- name: unique_identifier
  input: "The user message to send"
  config:                    # Optional: template vars for carter-ops
    bot_name: test-bot
    bot_email: test-bot@users.noreply.github.com
  expect:
    workflow_phases: [ASSESS, PLAN, APPROVE, EXECUTE, AUDIT, REPORT]
    commands_contain: ["git commit --author=..."]
    commands_not_contain: ["--dry-run", "--execute"]
    response_contains: ["keyword1", "keyword2"]
    response_not_contains: ["anti-pattern"]
```

### Adding a New Scenario

1. Add the YAML entry to the appropriate scenario file
2. For offline tests: the existing test classes pick it up automatically (if using parametrize) or add a test method
3. For live tests: add a test method that loads and evaluates the scenario

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `EVAL_MODEL` | Model to use for live evals | `claude-sonnet-5-5` (single-sourced in `evals/metrics.py`) |
| `EVAL_MAX_TOKENS` | Per-call completion cap | `4096` |
| `EVAL_METRICS_OUT` | Write the run's metrics summary JSON here | unset |
| `EVAL_RECORD` | Re-record adherence fixtures from a live run | unset |
| `ANTHROPIC_API_KEY` | API key for Anthropic (fallback if no Copilot auth) | — |
| `OPENAI_API_KEY` | API key for OpenAI (last resort fallback) | — |

Note: If you're logged into `gh` or `opencode`, no env vars are needed at all.

## CI Integration

For CI, run only offline evals (no API costs, deterministic):

```yaml
- name: Carter Evals (offline)
  run: uv run pytest evals/ -m "not live" -v
```

Live evals run on a weekly cron in
[`.github/workflows/evals-live.yml`](../.github/workflows/evals-live.yml).

## Extending the Framework

### Adding a new skill eval

1. Add scenario to `evals/scenarios/skills.yaml`
2. Add offline content check to `TestSkillPatternCoverage` in `test_skills.py`
3. (Optional) Add live eval to `TestLiveSkillCorrectness` in `test_live.py`

### Adding a new routing scenario

1. Add scenario to `evals/scenarios/routing.yaml`
2. The existing `TestRoutingScenarios` class picks it up automatically
