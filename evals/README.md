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
# Run offline evals (fast, no auth needed)
uv run --with pytest --with pyyaml pytest evals/ -m "not live" -v

# Run live evals (uses your existing Copilot auth automatically)
uv run --with pytest --with pyyaml --with httpx pytest evals/ -v

# Run only routing evals
uv run --with pytest --with pyyaml pytest evals/test_routing.py -v

# Run only skill correctness evals
uv run --with pytest --with pyyaml pytest evals/test_skills.py -v

# Override model for live evals
EVAL_MODEL=gpt-4o uv run --with pytest --with pyyaml --with httpx pytest evals/test_live.py -v
```

## Authentication

Live evals need an LLM. Authentication is resolved automatically in this order:

1. **GitHub Copilot** (preferred) — uses your existing `opencode` or `gh` CLI auth. No extra setup needed.
2. **ANTHROPIC_API_KEY** — env var with an Anthropic key
3. **OPENAI_API_KEY** — env var with an OpenAI key

If you're already using Copilot CLI or OpenCode, live evals work out of the box.

## Architecture

```
evals/
├── conftest.py          # Shared fixtures (repo paths, scenario loading)
├── pytest.ini           # Pytest config (live marker)
├── judge.py             # LLM-as-judge for qualitative evaluation
├── test_routing.py      # Offline: routing table completeness & accuracy
├── test_skills.py       # Offline: skill content correctness
├── test_live.py         # Live: actual model behavior evaluation
└── scenarios/
    ├── routing.yaml     # Routing dispatch scenarios
    ├── carter_ops.yaml  # Carter-ops workflow scenarios
    ├── skills.yaml      # Skill correctness scenarios
    └── e2e.yaml         # End-to-end multi-agent scenarios
```

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

### LLM-as-Judge (`judge.py`)

For qualitative criteria that can't be checked with `assert "X" in response`:

- Is the explanation accessible to non-experts?
- Does the code review cover security dimensions?
- Is the architecture diagram comprehensive?

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
    commands_not_contain: ["carter-ops git-flow --execute"]
    response_contains: ["keyword1", "keyword2"]
    response_not_contains: ["anti-pattern"]
    quality: [rubric_criterion_1, rubric_criterion_2]
```

### Adding a New Scenario

1. Add the YAML entry to the appropriate scenario file
2. For offline tests: the existing test classes pick it up automatically (if using parametrize) or add a test method
3. For live tests: add a test method that loads and evaluates the scenario

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `EVAL_MODEL` | Model to use for live evals | `claude-sonnet-4-20250514` |
| `EVAL_JUDGE_MODEL` | Model for LLM-as-judge | `claude-sonnet-4-20250514` |
| `ANTHROPIC_API_KEY` | API key for Anthropic (fallback if no Copilot auth) | — |
| `OPENAI_API_KEY` | API key for OpenAI (last resort fallback) | — |

Note: If you're logged into `gh` or `opencode`, no env vars are needed at all.

## CI Integration

For CI, run only offline evals (no API costs, deterministic):

```yaml
- name: Carter Evals (offline)
  run: uv run --with pytest --with pyyaml pytest evals/ -m "not live" -v
```

For periodic quality checks (weekly cron job):

```yaml
- name: Carter Evals (live)
  run: uv run --with pytest --with pyyaml --with httpx pytest evals/ -v
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}  # Or use Copilot token
```

## Extending the Framework

### Adding a new skill eval

1. Add scenario to `evals/scenarios/skills.yaml`
2. Add offline content check to `TestSkillPatternCoverage` in `test_skills.py`
3. (Optional) Add live eval to `TestLiveSkillCorrectness` in `test_live.py`

### Adding a new routing scenario

1. Add scenario to `evals/scenarios/routing.yaml`
2. The existing `TestRoutingScenarios` class picks it up automatically

### Adding a qualitative eval

1. Define the rubric criteria in the scenario YAML
2. Use `judge.judge_response()` in your test:
   ```python
   from evals.judge import judge_response

   result = judge_response(response, rubric=["clear", "actionable"], context=user_input)
   assert result.passed
   ```
