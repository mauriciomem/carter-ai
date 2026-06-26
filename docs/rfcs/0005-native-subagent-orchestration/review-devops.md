# Review: RFC-0005 — devops

## Round 1 — 2026-06-26 — reviewed revision 2 — verdict: request-changes

*Advisory delta review (ADR-0004 §D5): informs the maestro's synthesis; not a vote. Scope: model/runtime constraints, CI impact, the `/fleet` + effort story, and operational footguns.*

**Bottom line.** The RFC's biggest strength is also a devops liability: it correctly discovers that **effort is global-only and `model:` is per-target-shaped**, but it then hands the operator a config (`models:` block) that *looks* like it controls runtime behavior while the actual levers (effort, subscription, the global CLI flag) live outside Carter. Two blockers on making that boundary operationally honest, plus a CI/cost note.

### Blockers

**D1 — the "global effort recommendation" is unactionable as written.** §2 says "run thinkers at `--effort xhigh`, implementers at `--effort medium`" — but `--effort` is **one global flag per process**. You cannot run *thinkers at xhigh and implementers at medium in the same session* — the whole point of the per-tier split is undeliverable on effort, only on model. The RFC half-says this but the recommendation reads like you can have both. **State the operational truth plainly:** in one Carter session there is a *single* effort; pick it for the dominant workload (recommend `high` as the all-rounder, since `xhigh` errors on Haiku and over-spends on implementers, and `medium` under-serves the thinkers). The per-tier *effort* is aspirational pending the open VS Code/CLI issues; only the per-tier *model* is real today. An operator needs that sentence to set their flag correctly.

**D2 — `/fleet` is documented but its constraint isn't carried into the design.** §1 correctly notes `/fleet` subagents "don't inherit chat history — prompts must be self-contained." That's not just a doc note — it means a maestro that delegates via `/fleet` **cannot** rely on the session-bootstrap context (active plans, knowledge files) the maestro template loads ([carter-maestro.md.j2:67-100]). If we document `/fleet` as the Copilot-CLI orchestration path, the maestro prose must tell it to **pass plan/knowledge context into the `/fleet` prompt explicitly**, or cross-domain `/fleet` runs will silently lose Carter's state. Add this to §1 or it's a latent prod bug on the one target where orchestration is "parallel."

### CI / cost / ops notes (fold to plan)

- **CI model cost.** P4-eval runs a real model against a real plan — that's **billed API calls in CI** (or a recorded fixture). RFC-0002's suite was deterministic/offline ([README.md:193] "467 tests" run on every PR). An eval that hits the API can't gate every PR without cost/flakiness. Decide: nightly/manual eval (not per-PR) with a recorded-transcript fast path in CI. State it, or P4-eval silently makes CI expensive and flaky.
- **Model-name drift.** The Carter→target name table (Q2.2) is a **maintenance liability** — display names ("Claude Sonnet 4.6") and IDs (`anthropic/claude-sonnet-4-6`) change with each release, and a wrong string = silently dead agent (E2). Treat that table like the MCP server-name mapping: one home, a test that it's non-empty per shipped role, and a `MODEL LAUNCH`-style sync marker so the next model bump updates it.
- **`mode:` cleanup (S2).** Concur with keeping it for OpenCode; just confirm the plan doesn't *remove* it (OpenCode's primary/subagent split is load-bearing) while documenting it's ignored on VS Code.

### Runtime scan — otherwise clean
- Native dispatch primitives (§1) are the correct per-target mechanisms; `permission.task` only applies to `mode: subagent`/`all` invokers — confirm the maestro emits `mode: primary` **and** the OpenCode `permission.task` (primary can invoke; the key applies to the invoker). ✓ (verify in P3)
- `_TARGET_ENFORCES_GATES` re-eval (S7) is correct and overdue — Copilot CLI `hooks` preToolUse genuinely enforces; the table predates it. ✓
- Time-awareness via `date` (§6a) is the right runtime-agnostic call; no infra impact. ✓

**Verdict rationale.** D1/D2 are operational-honesty gaps: the RFC discovered the right constraints but didn't propagate them into what the operator/maestro actually does. Both are a few sentences. The CI-cost note is the one that bites later if unaddressed. Re-review on r3.
