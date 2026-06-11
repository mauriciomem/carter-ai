# Review: RFC-0002 — architect

## Round 1 — 2026-06-11 — reviewed revision 1 — verdict: request-changes

*Advisory review (ADR-0004): this informs the maestro's synthesis; it is not a vote and does not edit the RFC body.*

**Bottom line.** The two-axis policy model (level × per-agent allowlist over a fixed taxonomy) is genuinely coherent, honest, backward-compatible, and well-phased — this is good architecture. But the load-bearing premise *"Carter cannot intercept a tool call"* ([README.md#L41](docs/rfcs/0002-risk-based-strictness-policy/README.md#L41)) is materially inaccurate for 2026: the configs Carter emits **can** intercept deterministically (OpenCode `permission: deny`, Copilot CLI `hooks` preToolUse, VS Code MCP `sandbox`/`hooks`). That false premise propagates into an overly-pessimistic "degrade to prose" emission story ([#L45](docs/rfcs/0002-risk-based-strictness-policy/README.md#L45)) and an alternatives table that never considers emitting native interceptors ([#L180](docs/rfcs/0002-risk-based-strictness-policy/README.md#L180)). Fix the framing + add hooks as a first-class emission target + patch two taxonomy gaps and this is approvable.

---

## 1. Design coherence of the `policy` model — mostly sound

The model composes cleanly on two axes that meet at one cell:
- **level → gate** (per category) and **agent → allowed-categories** (deny-by-default), combined as `min(level gate, allowlist)` per category ([#L122](docs/rfcs/0002-risk-based-strictness-policy/README.md#L122)). Effectively a 2D table (agents × categories), level sets the column default, allowlist masks cells to `deny`. That is a coherent mental model, not overlapping pillars.

Friction points (non-fatal):
- **`gate` is overloaded — concept *and* value.** The section is about "gates," yet `gate` is also one of the four gate *values*, defined as a compound `ask` **+** required handoff/checkpoint ([#L90](docs/rfcs/0002-risk-based-strictness-policy/README.md#L90)). One token names both the umbrella concept and a specific compound action. Recommend renaming the value (e.g., `checkpoint`) so "gate" stays the generic term and the value names exactly one mechanism.
- **allowlist × level at `strict` locks out the sole actor.** devops is the only R3/R5 agent ([#L115](docs/rfcs/0002-risk-based-strictness-policy/README.md#L115)), but `strict` sets R3=`deny` / R5=`deny` ([#L98](docs/rfcs/0002-risk-based-strictness-policy/README.md#L98), [#L100](docs/rfcs/0002-risk-based-strictness-policy/README.md#L100)). Net: at `strict`, *every* infra-mutate / destructive action is an escape-hatch override. Possibly intended ("regulated = every apply is auditable"), but it directly tensions with the override-fatigue goal in Q11. State the intent explicitly.
- **Emission is where the clean model meets mess.** The allowlist denies *categories*, but frontmatter emits *tool names*; you must expand each allowed category into its full tool set per agent. That cross-product is the real drift surface `carter check` must guard — worth naming as the model's cost.

## 2. Hybrid vs alternatives — right call, but the table has a hole

- Rejecting **globally-rigid** (kills speed → users disable) and **prompt-only** (the current problem) is correct.
- Rejecting the **runtime proxy** ([#L180](docs/rfcs/0002-risk-based-strictness-policy/README.md#L180)) is also correct — Carter building its *own* interception runtime is the wrong identity.
- Keeping `quality_gate` separate (post-review ≠ pre-action authorization) is the right seam.

**Gap (blocking):** the table conflates "Carter intercepts" (proxy — rightly rejected) with "Carter emits config the *target* enforces" (native hooks/permission — never considered). These are architecturally different: the latter keeps Carter a pure scaffolder while still achieving deterministic deny. A missing alternative row — **"emit native pre-action hooks / permission-deny (target-run interception)"** — would score *high enforcement + low complexity + stays-scaffolder*, which materially changes the conclusion for `deny` on R2/R3/R5. The hybrid is still right; the analysis that justifies degrading to prose is incomplete.

## 3. "Scaffolder-not-runtime" framing — the central judgment

**Keep the identity, fix the premise.** The sentence at [#L41](docs/rfcs/0002-risk-based-strictness-policy/README.md#L41) silently fuses two claims:
- (a) *Carter-the-process* can't intercept a call at runtime — **TRUE** (Carter isn't running when the agent runs).
- (b) *The config Carter emits* can't intercept a call — **FALSE in 2026.** OpenCode `permission: deny` is a hard runtime deny; Copilot CLI `hooks` preToolUse can **block** deterministically; VS Code MCP `sandbox` + agent `hooks` (Preview) gate filesystem/network/tool calls.

The honest, accurate framing:

> Carter is a scaffolder, not a runtime — it never sits in the tool-call path. **But the config it emits *does* sit in that path:** OpenCode `permission`, Copilot CLI `hooks`, VS Code `sandbox`/`hooks` intercept deterministically because the *target* enforces them. Enforcement = emit native interceptors + lint. The ceiling is the target's primitives, not Carter's nature.

**Should hooks be a first-class emission target? Yes — for `deny`/`block` on R2/R3/R5**, precisely the categories where prose is most dangerous. Concrete asks:
- Add a `hooks` row to the §4 emission matrix and re-rank the ladder: **native deny/block → native ask → prose backstop** (today prose is treated as the routine fallback at [#L45](docs/rfcs/0002-risk-based-strictness-policy/README.md#L45)).
- The §4 matrix also *under-claims* verified reality: VS Code `tools:` is an **enforced** allowlist (not "list" / "list-only" — [#L127](docs/rfcs/0002-risk-based-strictness-policy/README.md#L127)), and **all three** targets support per-agent MCP scoping ([#L129](docs/rfcs/0002-risk-based-strictness-policy/README.md#L129) hedges "verify"). Correcting these *strengthens* the proposal — the "per-target inequality" worry shrinks.
- **Caveat (don't over-rotate):** VS Code `hooks` are Preview (`chat.useCustomAgentHooks`). Treat hooks as "first-class where GA (OpenCode permission, Copilot CLI hooks), preview-flagged where Preview (VS Code)." Do not make hooks a hard dependency — make them the documented deterministic path where available.

This is the one change that, if not made, leaves the RFC's core enforcement story resting on an inaccurate constraint.

## 4. Taxonomy (R0–R6) — good cut, two real gaps + a calibration question

The 7-way flat enum is a reasonable operational cut; a flat enum over a matrix is the right simplicity trade. Edge-case rulings are mostly sound: amend-published = R5 ✓ ([#L231](docs/rfcs/0002-risk-based-strictness-policy/README.md#L231)), `.env` read = R4 ✓ ([#L99](docs/rfcs/0002-risk-based-strictness-policy/README.md#L99)) — and R4 happily aligns with OpenCode denying `.env` reads by default, so emission reinforces the taxonomy. But:

- **Missing precedence rule (blocking-lite).** Categories overlap: `git push --force` is R2 ∩ R5 (table files it R5 at [#L100](docs/rfcs/0002-risk-based-strictness-policy/README.md#L100)); `terraform destroy` is R3 ∩ R5 (table files it R3 at [#L98](docs/rfcs/0002-risk-based-strictness-policy/README.md#L98)). Two destructive-class actions land in different categories with no stated tie-breaker. Add an explicit **"most-restrictive category wins"** rule and apply it consistently.
- **No network-egress / exfiltration category (gap).** `webfetch`/`websearch`/arbitrary outbound POST has no home: it's not `read`, and `external-publish` (R6) is scoped to *content* (Slack/PR/Jira — [#L101](docs/rfcs/0002-risk-based-strictness-policy/README.md#L101)). Yet **R4 secret read + arbitrary network egress = the actual breach path**, and OpenCode exposes a distinct `webfetch` permission for exactly this. Either add an egress category or explicitly fold egress into an existing one and say why.
- **R4 never reaches `deny` (calibration DECIDE).** R4 tops out at `gate` even at `strict` ([#L99](docs/rfcs/0002-risk-based-strictness-policy/README.md#L99)), while R3/R5 reach `deny`. For "regulated/prod-critical," uncontrolled secret access is often *the* compliance line — is secret-access truly lower-risk than infra-mutate at strict? Reconsider R4=`deny` at strict (override-gated).
- **devops allowlist omits R4 ([#L115](docs/rfcs/0002-risk-based-strictness-policy/README.md#L115)).** Deploys routinely need secret reads (vault, `.env`, provider creds). As written, devops needs an override for *every* secret read. Intended (full auditability) or an oversight? Resolve.

## 5. Conceptual seams vs existing config

- **vs `personality.skepticism` (Q4) — clean ✓.** "skepticism = tone, policy = enforcement, policy wins on conflict" is the right separation, and moving the maestro risk table from `skepticism`-gated to always-present policy-driven ([#L138](docs/rfcs/0002-risk-based-strictness-policy/README.md#L138)) is correct. Make explicit that skepticism then only modulates *wording*, never whether a gate exists. Grounds against today's `skepticism == "scaled"` trigger ([templates/agents/carter-maestro.md.j2](templates/agents/carter-maestro.md.j2#L170)).
- **vs `quality_gate` (Q5) — clean ✓.** Genuinely different lifecycle points (pre-action authz vs post-implementation review); reusing the severity vocabulary is good consistency.
- **vs `redaction` (Q16) — slightly muddy ⚠.** Tying the R6 gate *strength* to `redaction.enabled` ([#L255](docs/rfcs/0002-risk-based-strictness-policy/README.md#L255)) means two independent flags (level + redaction.enabled) jointly determine one gate — and disabling redaction *silently weakens* the R6 gate. Cleaner seam: **level alone** sets the R6 gate; redaction is an orthogonal transform on published content. Decouple.
- **Handoff (Q10) — reinvents a native primitive.** Q10 treats handoff as a prose-only advisory protocol with platform `ask` as the only backstop ([#L236](docs/rfcs/0002-risk-based-strictness-policy/README.md#L236)). Native primitives exist: OpenCode `permission.task` (which subagents are callable) and VS Code `handoffs:` frontmatter. The advisory protocol should *layer on* these, not substitute for them.

## 6. DECIDE items (human call — advisory positions)

- **DECIDE — Q18 one RFC vs split ([#L260](docs/rfcs/0002-risk-based-strictness-policy/README.md#L260)).** Architecturally I endorse **one**: the pillars are interdependent (a taxonomy without gates is inert; levels without a taxonomy are meaningless; `min(level, allowlist)` couples them). P1–P3 phasing is the right way to land it incrementally. Emission/lint are the only separable parts, but splitting them buys little.
- **DECIDE — Q19 ADR numbering ([#L262](docs/rfcs/0002-risk-based-strictness-policy/README.md#L262)).** Non-architectural bookkeeping; should not gate the RFC. The "reserved" backup ADR is informal/unwritten. Recommend **assign the next free number at write/acceptance time** — don't pre-allocate ADR-0005 to either.
- **DECIDE — Q6 default level.** `loose`-preserve (no behavior change) vs `guarded`-nudge (migration note). Product call; both are defensible — `loose` for existing/omitted config is the conservative default given P1 ships no behavior change.
- **DECIDE — Q3 token blast radius ([#L213](docs/rfcs/0002-risk-based-strictness-policy/README.md#L213)).** Accept residual risk vs invest in scoped tokens. Note: dropping "read-only" wording where unenforceable ([#L140](docs/rfcs/0002-risk-based-strictness-policy/README.md#L140)) is honest and correct — today the shared full-scope `GITHUB_TOKEN` makes "read-only" fiction ([carter/installer.py](carter/installer.py#L271)). The hooks/permission-deny path (focus area 3) *narrows* this residual by blocking write *tool names* even with a write-capable token.
- **DECIDE — Q14 global agents.** Static `agents/*.md` install with no `carter.yaml` in scope; baked-`guarded` defaults vs a global policy file read at install. Baking is simpler and matches "agents are re-emitted, never hand-edited."

---

## Blocking concerns (request-changes)

1. **Reframe the premise ([#L41](docs/rfcs/0002-risk-based-strictness-policy/README.md#L41), [#L203](docs/rfcs/0002-risk-based-strictness-policy/README.md#L203)).** Split "Carter-process can't intercept" (true) from "emitted config can't intercept" (false). This is load-bearing — it drives the whole emission/degradation design.
2. **Add native hooks/permission-deny as a first-class emission target** for `deny` on R2/R3/R5, with a re-ranked ladder (native deny → native ask → prose) and a Preview-maturity caveat for VS Code hooks.
3. **Correct the §4 emission matrix to verified reality ([#L127](docs/rfcs/0002-risk-based-strictness-policy/README.md#L127)–[#L129](docs/rfcs/0002-risk-based-strictness-policy/README.md#L129)):** VS Code `tools:` is *enforced* (not list-only); all three targets do per-agent MCP scoping. This strengthens, not weakens, the proposal.
4. **Taxonomy fixes ([#L90](docs/rfcs/0002-risk-based-strictness-policy/README.md#L90), [#L98](docs/rfcs/0002-risk-based-strictness-policy/README.md#L98)–[#L101](docs/rfcs/0002-risk-based-strictness-policy/README.md#L101), [#L115](docs/rfcs/0002-risk-based-strictness-policy/README.md#L115)):** add an explicit most-restrictive-wins precedence rule; add or explicitly reject a network-egress/exfiltration category; resolve the devops-missing-R4 allowlist gap.

## Non-blocking (would improve coherence)

- Rename the `gate` *value* (e.g., `checkpoint`) to resolve the concept/value collision.
- Reconsider R4=`deny` at `strict`.
- Decouple R6 gate strength from `redaction.enabled`.
- Layer the Q10 handoff protocol on native `handoffs:` / `permission.task` rather than prose-only.
- State the intended strict-mode behavior for devops (every R3/R5 → override) explicitly against Q11.
