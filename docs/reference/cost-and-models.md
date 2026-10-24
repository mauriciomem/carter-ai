# Running Carter without breaking the bank

*A plain-language guide to what Carter costs you, why, and how to run it on cheaper
models without losing quality. The design record is
[ADR-0008](../adr/0008-mcp-cost-and-security.md); this doc is for people who **use** Carter.*

Last reviewed: 2026-10-24.

---

## The one thing to understand first

**Carter is a scaffolder, not a program that runs your AI.** When you run `carter
install` or `carter init`, Carter writes a pile of static files — agent definitions,
skills, and MCP server configs — into your editor or CLI, and then it *exits*. From that
point on, your **harness** (GitHub Copilot, OpenCode, or VS Code) is what actually talks
to the model.

Why this matters for your bill: Carter can only influence two things about cost —

1. **How much text it puts in front of the model** (agent prompts, skill descriptions,
   tool schemas), and
2. **Which model each agent is told to use.**

Everything else that saves money — reusing cached context, summarizing long
conversations, loading files only when needed — is your harness's job, not Carter's. So
this guide focuses on the two knobs Carter *does* control.

## How you're billed (both harnesses charge for tokens)

Both supported harnesses now bill by **tokens** — the chunks of text the model reads and
writes:

| | **GitHub Copilot** | **OpenCode** |
|---|---|---|
| You pay for | tokens → "AI Credits" (1 credit = $0.01) | tokens (your own API key) |
| Bigger prompts cost… | more | more |
| A more expensive model costs… | **more, per token** | **more, per token** |
| Tool calls & agent-to-agent hops | cost extra (they re-send context) | cost extra |

The key takeaway: **the model you choose is a multiplier on every token.** A cheaper
model doesn't just cost less once — it costs less on *everything* that agent reads and
writes, for the whole session. That's why model choice is the biggest lever you have.

## Where Carter's tokens actually go

Rough sizes (they drift as the project grows):

- **Always loaded, every request:** global instructions + all skill *descriptions* ≈
  **~1.4k tokens**, plus the primary orchestrator's own prompt — Maestro ≈ **3.2k
  tokens**, since it carries the routing table *and* the human-facing protocol blocks
  (session bootstrap, quality gate, knowledge capture, and the two communication
  registers). Everything else is paid for only when it's used.
- **Loaded when an agent is used:** that one agent's prompt ≈ **0.4k–1.4k tokens**.
  Specialists deliberately do *not* carry the communication registers — they inherit
  the concise / cite-sources / junior-clarity baseline from the global instructions,
  which costs nothing extra per dispatch.
- **Loaded on demand:** a skill's full body (only when that skill fires), and its
  reference files (only when needed). This is "progressive disclosure" — Carter doesn't
  pay for a skill you don't use.
- **The big one — MCP tool schemas:** when GitHub/Terraform/Atlassian MCP servers are
  wired in, their tool definitions are the **largest single chunk** — the GitHub server
  alone is ~4k tokens *per request*, larger than all of Carter's prose combined.

So the two places real money leaks are: **(1) expensive models on agents that don't need
them**, and **(2) MCP servers you're not using but still shipping.**

## The current defaults

**Models.** Carter groups agents into two tiers:

| Tier | Model (default) | Agents |
|------|-----------------|--------|
| Thinkers | **Opus 5.5** (frontier, most expensive) | maestro, architect, learner, security |
| Implementers | **Sonnet 5.5** (mid-tier, cheaper) | engineer, devops, **pm**, **narrator** |

That's **4 of 8 agents on the frontier model** — down from 6. `pm` and `narrator` moved
to Sonnet by default: their work is highly *structured* — narrator's
redaction is rule-bound, pm's planning follows a fixed schema — so a mid-tier model,
guided by Carter's skills, does the job at a fraction of the cost. Both had to **clear an
adherence eval on Sonnet** before the default moved (see below; the recorded runs are on
Sonnet 4.6). The four remaining
thinkers stay on Opus because their work is open-ended: maestro routes everything,
architect and security reason deeply, learner writes free-form explanation.

**MCP servers.** `carter install --mcp` wires the three servers (GitHub, Terraform,
Atlassian). MCP tool schemas are the **largest per-request token surface** — larger than
all of Carter's prose combined — so shipping one you never use is pure waste. You can
install a **subset**:

```bash
carter install --mcp --mcp-servers github          # just GitHub — skips terraform+atlassian
carter install --mcp --mcp-servers github,terraform
carter install --mcp                                 # all three (default)
```

The GitHub server is the official `github/github-mcp-server` run **read-only** via Docker
(a security hardening that costs ~68% more GitHub tokens than the old server, accepted
deliberately — see [ADR-0008](../adr/0008-mcp-cost-and-security.md)). "Read-only" removes the MCP *write* surface only; shell
`gh`/`git` writes still work, governed by the strictness policy.

## Choosing a cost profile

The cheaper default above is already applied out of the box. If you want to push cost
down further — or trade it back for maximum quality — set a **`profile:`** in your
workspace `carter.yaml`:

| `profile:` | What it does | When |
|------------|--------------|------|
| *(unset)* | The shipped default: pm + narrator on Sonnet, the rest as tiered | The balanced default |
| `budget` | The default **plus** learner → Sonnet | You want the lowest cost that still cleared review |
| `quality` | **Every** agent on Opus (the pre-cost-optimization behavior) | You prioritize quality over cost |

Set it at scaffold time:

```bash
mkdir -p ~/my-project
carter init ~/my-project --profile budget      # or: quality
```

…or add it to an existing `carter.yaml` and re-render:

```yaml
profile: budget
```

```bash
carter update   # re-render the agent files with the new profile
```

### Fine-tuning individual agents

A `profile:` re-tiers everyone at once. To change **one** agent, add a per-agent override
— it wins over the profile and the tier (resolution order is
`overrides > profile > tier > default`):

```yaml
models:
  overrides:
    engineer:
      copilot: "Claude Haiku 5.5"          # cheapest tier for well-specified impl work
      opencode: "anthropic/claude-haiku-5-5"
```

Then re-run `carter update`. Haiku is the cheapest option for well-specified
implementer work (`engineer`/`devops`).

## Prove a downgrade is safe before you commit to it

You don't have to guess whether a cheaper model still does the job. Carter ships an
**adherence eval** that scores whether an agent faithfully followed its plan:

```bash
uv run pytest evals -m "not live" -v
```

The grader ([evals/adherence.py](../../evals/adherence.py)) is deterministic and free —
it replays a recorded transcript and checks that ≥90% of the plan's requirements were met
with zero critical failures. This is exactly how `pm` and `narrator` earned their move to
Sonnet: each has a recorded scenario (narrator's checks that redaction holds in the
shipped output; pm's checks the plan carries scope/milestones/definition-of-done). If you
downgrade another agent, add a scenario for it, run the eval, and only keep the change if
it still passes.

## Other ways to spend less

### Don't install MCP servers you won't use

Install the **subset** you need with `--mcp-servers` (e.g. `--mcp-servers github`), and
only set the tokens (`GITHUB_TOKEN`, `TFE_TOKEN`) for the servers you wire (Atlassian
authenticates via OAuth).
An unused server adds zero tool-schema tokens.

### Cut round-trips

Every time the maestro hands off to a specialist, the context gets re-sent — that's more
tokens. You can reduce hops by:

- **`@`-mentioning the specialist directly** when you already know who you need (e.g.
  `@carter-engineer review this`) instead of routing through the maestro.
- **Being specific up front** so an agent doesn't have to ask clarifying questions and
  redo work. Carter's TDD-first and plan-first skills exist partly to prevent these retry
  loops.

## The deeper idea: structure replaces raw model power

The reason downgrading works at all is that **Carter pushes the "thinking" into its
scaffolding.** A weaker model succeeds when the task is already broken into steps, the
definition of "done" is written down and checkable, and only the relevant context is
loaded. That's exactly what Carter's skills do — `carter-plan` decomposes work into a
plan with verifiable `must_haves`, `carter-test-first` pins down behavior before code,
and progressive disclosure keeps context lean.

So the cost-conscious way to use Carter is: **let one strong model (or one careful
planning pass) decompose the problem, then let cheaper models execute the well-defined
pieces.** You spend frontier-model money once, on the hard thinking, not on every step.

## Quick reference

| Want to… | Do this |
|----------|---------|
| Spend even less | `profile: budget` in `carter.yaml` (or `carter init --profile budget`), then `carter update` |
| Restore max quality | `profile: quality` (all agents on Opus) |
| Tune one agent | Add a `models.overrides` entry, run `carter update` |
| Check quality held up | `uv run pytest evals -m "not live"` |
| Avoid MCP token cost | Only `--mcp` the servers you use; only set their tokens |
| Reduce hops | `@`-mention specialists directly; be specific up front |
| Understand the trade-offs | Read [ADR-0008](../adr/0008-mcp-cost-and-security.md) |
