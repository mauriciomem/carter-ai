---
step: 6
status: done
depends_on: [5]
files_modified: [evals/, tests/, .github/workflows/]
---

## Step 6 — P4-eval: implementer-adherence eval; gates the cheap-tier default

The reliability backstop. ADR-0010 D9. Empirically backs Sonnet-as-default and protects the
documentation-quality contract (the cheaper model must execute thinker docs faithfully).

### Tasks
- Add an **`evals/` scenario** that runs the **Sonnet 4.6** implementer tier against a thinker-produced
  plan (with real `must_haves`: named file paths, acceptance checks, step-level instructions) and grades
  adherence — fraction of `must_haves` satisfied + whether any critical step (acceptance check / named
  file / intent) was missed.
- **Pass-bar: ≥ 90% of `must_haves` satisfied AND 0 critical-step failures.** Below the bar = a
  regression in EITHER the model tier OR the doc quality; it blocks keeping/shipping the cheap tier as
  default, and the same bar gates any future cheaper-tier (e.g. Haiku) default.
- **Cadence (NOT per-PR live):** a nightly/manual runner hits the live API (billed); CI replays a
  **recorded transcript fixture** for determinism. Do NOT wire a live-API call into per-PR CI.
- Record the eval result alongside the plan; the cheap-tier default in Step 5 ships only once this
  clears the bar.

### Done when
- The `evals/` scenario exists and runs against a thinker plan, emitting an adherence score + a
  critical-failure count.
- A recorded fixture replays deterministically in per-PR CI (offline, free); the live runner is
  nightly/manual only — confirmed absent from the per-PR workflow.
- The recorded Sonnet 4.6 run clears **≥90% must_haves + 0 critical-step failures**; the result is
  recorded and the cheap-tier default (Step 5) is confirmed shippable.
- The doc-quality contract is stated in the eval (docs stay at the Opus bar regardless of executor).
