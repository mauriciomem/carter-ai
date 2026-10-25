# Carter evals

The evals check that Carter's agent and skill prompts say the right things and that
models follow them. They complement the unit tests in `tests/`
([Testing](../docs/contributing/testing.md)).

There are two kinds:

| Kind | Checks | Cost | Runs |
|------|--------|------|------|
| **Offline** | Prompt structure: routing tables, skill content, recorded sessions | Free, about a second | Every PR |
| **Live** | How a real model responds to the prompts | API charges, ~30 s per scenario | Weekly, or on demand |

## Run them

Always pass the `evals` path: `evals/pytest.ini` registers the `live` marker, and the
root configuration only collects `tests/`.

```bash
uv sync --extra dev                          # once
uv run pytest evals -m "not live" -v         # offline
uv run pytest evals -m live -v               # live (needs an API key)
uv run pytest evals/test_routing.py -v       # one file
EVAL_MODEL=<model-id> uv run pytest evals/test_live.py -v
```

Live evals read `ANTHROPIC_API_KEY`, or else `OPENAI_API_KEY`, from the environment
and skip when neither is set. They never use stored OpenCode or `gh` credentials.

| Variable | Purpose | Default |
|----------|---------|---------|
| `EVAL_MODEL` | Model for live evals | `claude-sonnet-5-5` (set in `metrics.py`) |
| `EVAL_MAX_TOKENS` | Output cap per call | `4096` |
| `EVAL_METRICS_OUT` | Write a JSON summary of tokens, latency and cost here | not set |
| `EVAL_RECORD` | Re-record the adherence fixtures from a live run | not set |

## Layout

```text
evals/
├── conftest.py            shared fixtures (paths, scenario loading)
├── pytest.ini             registers the live marker
├── adherence.py           adherence grader (deterministic, no model call)
├── metrics.py             token, latency and cost summary
├── test_routing.py        offline: routing table
├── test_skills.py         offline: skill content
├── test_metrics.py        offline: metrics
├── test_adherence.py      offline: replays recorded sessions
├── test_live.py           live: model behavior
├── test_adherence_live.py live: a real session, graded
├── fixtures/              recorded sessions (engineer, narrator, pm)
└── scenarios/             YAML scenarios (routing, ops, skills, adherence)
```

## What they check

**Routing** (`test_routing.py`): every agent has a row in Maestro's routing table,
no keyword routes to two agents, every scenario matches the table, and every agent
carries the `ops:` trigger line.

**Skills** (`test_skills.py`): the `ops:` flow lists its six phases in order
(assess, plan, approve, execute, audit, report); commits are signed, authored by the
user and credited with a `Co-authored-by:` trailer, never `--author`; skills have
frontmatter and cover their core topics; no skill teaches a retired approach.

**Live** (`test_live.py`): does the model show a plan and wait for approval, refuse
to run destructive commands on its own, route to the right agent, and follow the
skill's patterns?

## Adherence eval

This eval decides whether an agent can run on a cheaper model. It gives the agent a
plan written by a stronger model, with concrete `must_haves` (file paths, acceptance
checks, step instructions), and grades the result.

**It passes when at least 90% of the `must_haves` are met and no critical step is
missed.** A critical step is touching a named file, an acceptance check, or a key
instruction. A failure means either the model or the plan is not good enough; a
cheaper executor doesn't lower the bar for the plan.

- `test_adherence.py` replays the recorded sessions in `fixtures/` on every PR, with
  no API call.
- `test_adherence_live.py` runs a real session on the weekly schedule only.
- `EVAL_RECORD=1` with the live test overwrites the fixture with a fresh recording.

The Engineer, Narrator and PM run on the cheaper tier by default because their
recorded runs, made on Sonnet 4.6, pass this eval. The fixtures were not re-recorded
on the current default model.

## Scenarios

Scenarios live in `evals/scenarios/*.yaml`:

```yaml
- name: unique_identifier
  input: "The user message to send"
  config:                    # optional template values for the ops skill
    bot_name: test-bot
    bot_email: test-bot@users.noreply.github.com
  expect:
    workflow_phases: [ASSESS, PLAN, APPROVE, EXECUTE, AUDIT, REPORT]
    commands_contain: ["git commit -S", "Co-authored-by: ..."]
    commands_not_contain: ["--dry-run", "--execute"]
    response_contains: ["keyword1", "keyword2"]
    response_not_contains: ["anti-pattern"]
```

To add one:

- **Routing:** add it to `scenarios/routing.yaml`; `TestRoutingScenarios` picks it up.
- **Skill:** add it to `scenarios/skills.yaml`, add a content check to
  `TestSkillPatternCoverage` in `test_skills.py`, and optionally a live check to
  `TestLiveSkillCorrectness` in `test_live.py`.

## In CI

- [`ci.yml`](../.github/workflows/ci.yml) runs `pytest evals/ -m "not live"` on every
  PR.
- [`evals-live.yml`](../.github/workflows/evals-live.yml) runs the live evals every
  Monday with one model-provider secret (Anthropic, or OpenAI as a fallback) and a
  capped budget, and uploads the metrics as an
  artifact.
