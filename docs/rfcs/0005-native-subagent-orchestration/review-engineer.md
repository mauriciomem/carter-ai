# Review: RFC-0005 — engineer

## Round 1 — 2026-06-26 — reviewed revision 2 — verdict: request-changes

*Advisory delta review (ADR-0004 §D5): informs the maestro's synthesis; not a vote. Scope: implementation feasibility, test surface, and the security pass (trust boundaries, secrets, what the emitted config actually enforces).*

**Bottom line.** Feasible and mostly low-risk — the changes are concentrated in `config.py` (model + emission), `scaffold.py` (lint), templates/statics, and three test files, all of which already exist and are exercised. The phasing is sane. Two blockers on *enforcement honesty* (the recurring Carter failure mode), one on test coverage, and a security note on `permission.task`.

### Blockers

**E1 — `agents:`/`permission.task` is a security boundary; the RFC treats it as a feature.** §1 emits `agents: [carter-*]` (VS Code) and `permission.task: {'carter-*': allow}` (OpenCode). Good — but the RFC never states the **failure-open** risk: if Carter emits `agents: ['*']` or omits the key, the maestro can delegate to **any** agent in the workspace, including non-Carter ones the user installed. That breaks the deny-by-default posture RFC-0002 established. **Require the explicit allowlist (Q1.2 resolution) as a hard rule, not a recommendation**, and add a `carter check` lint that fails if the emitted `agents:`/`permission.task` is `*` or absent on the primary. This is the §1 analog of RFC-0002's "deny-by-default."

**E2 — the `model:` emission can't be verified, and the RFC half-admits it (Q2.3) then ships anyway.** Emitting `model: "Claude Sonnet 4.6"` when the user's Copilot plan doesn't include Sonnet produces a **silently broken agent** (foreign frontmatter is ignored — same failure class as the MCP glob in HANDOFF). The RFC's "emit + advisory" is acceptable *only if* the advisory is real: `carter check` must surface "agent X pins model Y; Carter cannot verify your subscription includes it." Without that, P4 ships a footgun. Make the advisory a **required** `carter check` output, not an open question.

**E3 — `temperature` is a live contradiction P4 makes worse, and it's tested as required.** S4 flags it; Q2.6 leaves it open. But P4 pins `model: claude-opus-4-8`-class models whose API **rejects `temperature`** — so we'd emit, on the same agent, a model that 400s on a field we also emit and *assert is present* ([test_parity.py:141]). The runtimes likely strip it, but we'd be shipping a self-contradictory frontmatter and a test that enforces the contradiction. **Resolve Q2.6 in this RFC, not the plan:** drop `temperature` emission (and its parity assertion) when a model that rejects it is pinned, or drop it wholesale and document that effort/temperature are runtime-owned. I lean drop-wholesale — it's dead weight on every modern target.

### Test surface (must be in the plan's must_haves)

- **S3 body-parity for `runSubagent`** — the existing body tests ([test_parity.py:172-220]) cover `read-only`/`full access` only; add a `runSubagent`-absent assertion or the fiction can silently return (it already drifted once).
- **`loose`→`guarded` migration test** (§3 Q3.1) — assert an existing `carter.yaml` with `level: loose` loads as `guarded` + emits the notice, and that `_validate_policy` rejects `loose` as an *explicit new* value if you go the hard-error route. Pick one and test it.
- **2-level × 4-category gate map** — `RISK_TAXONOMY` shrinks on both axes; `test_config.py`/`test_policy_lint.py`/`test_scaffold.py` (27 `loose` refs + the R-key tables) need full re-baseline, not patching. Budget for it.
- **P4-eval** — concur with architect: state the pass-bar. An eval with no threshold can't gate.

### Security scan — otherwise clean
- No new token surface; `model:`/`agents:`/`permission.task` carry no secrets. ✓
- Time-awareness via `date` tool/instruction (§6a) — note the `date` command output is untrusted-ish but low-risk; the cache-poisoning avoidance (no interpolation) is the right call and also the *secure* call. ✓
- Dropping `loose` slightly *raises* the security floor (no more "advisory that does nothing" default). ✓

**Verdict rationale.** E1/E2/E3 are all the same Carter anti-pattern — emitting config that looks enforced but isn't, or contradicts itself. RFC-0002 earned its acceptance by being honest about that; r2 reintroduces three instances. All three are resolvable with a lint + a Q-resolution, no redesign. Re-review on r3.
