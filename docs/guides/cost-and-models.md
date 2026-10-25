# Cost and models

This page explains what drives your AI bill when you use Carter, and the settings
that change it.

## Who talks to the model

Carter is an installer, not a runtime. `carter install` and `carter init` write
files and exit. From then on **OpenCode** sends every request to the model provider
you configured, and the provider bills you by **tokens**: the chunks of text the
model reads and writes.

Carter influences your bill in two ways:

1. **How much text goes into each request:** agent instructions, skill
   descriptions, MCP tool lists.
2. **Which model each agent uses.** A pricier model costs more for every token that
   agent reads or writes, for the whole session. This is the biggest lever.

Caching, summarizing long conversations and similar savings are OpenCode's job.

## Where the tokens go

| Part | When it is sent |
|------|-----------------|
| Global rules and the list of skill descriptions | Every request |
| Maestro's instructions (routing table, review and session rules) | Every request to Maestro |
| A specialist's instructions | Only when that specialist runs |
| A skill's full text | Only when the skill is loaded |
| MCP tool lists | Every request, for every configured server |
| Your conversation and files | Every request, and again for each subagent handoff |

So most avoidable cost comes from **expensive models on agents that don't need
them** and **MCP servers you don't use**.

## Default models

Agents are split into two tiers:

| Tier | Default model | Agents | Why |
|------|---------------|--------|-----|
| Thinkers | `anthropic/claude-opus-5-5` | Maestro, Architect, Learner, Security | Open-ended reasoning, routing |
| Implementers | `anthropic/claude-sonnet-5-5` | Engineer, DevOps, PM, Narrator | Well-defined, structured work |

PM and Narrator follow fixed formats (plan schema, redaction rules), so a cheaper
model does the job. Both passed an adherence test on the cheaper model before the
default changed.

`carter check` prints the model of every agent. Carter can't check that your
provider offers those models; if it doesn't, change them as described below.

## Choose a profile

In a workspace, a **profile** moves several agents at once:

| `profile` | Effect | Use it when |
|-----------|--------|-------------|
| *(not set)* | The defaults above | Balanced |
| `budget` | Defaults, plus Learner on the cheaper model | Lowest cost that still passed review |
| `quality` | Every agent on the thinker model | Quality matters more than cost |

```bash
carter init ~/my-project --profile budget
```

Or add it to an existing `.carter/carter.yaml` and regenerate:

```yaml
profile: budget
```

```bash
carter update
```

## Change one agent, or the models themselves

Override a single agent. This wins over the profile:

```yaml
models:
  overrides:
    engineer: anthropic/claude-haiku-5-5
```

Or point a whole tier at other models. `opencode models` lists the ones your
providers offer:

```yaml
models:
  thinkers: anthropic/claude-opus-5-5
  implementers: anthropic/claude-haiku-5-5
```

Each value is one OpenCode model string, `provider/model`, with an optional
`#variant` (for example a reasoning level). The order of precedence is
`overrides` → `profile` → tier → `default`. Run `carter update` afterwards.

Profiles and model settings apply to workspace agents only. The global agents from
`carter install` always use the defaults.

## Test a cheaper model before you switch

Carter's repository contains an **adherence eval**: it replays a recorded session
and checks that the agent met at least 90% of the plan's requirements, with no
critical misses. It is free and runs offline. If you move another agent to a cheaper
model, add a scenario for it and run the evals; see the
[eval framework](../../evals/README.md).

## Other ways to spend less

- **Configure only the MCP servers you use:** `carter install --mcp --mcp-servers github`.
- **Name the specialist** you want, so Maestro doesn't have to work it out.
- **Be specific up front**, so agents don't ask questions and redo work.
- **Plan once with a strong model, execute with cheaper ones.** A plan with a
  checkable definition of done (`carter-plan`) and tests written first
  (`carter-test-first`) let a cheaper model finish the work reliably.

## Next

- [Configuration reference](../reference/configuration.md#models)
- [MCP servers](mcp-servers.md)
