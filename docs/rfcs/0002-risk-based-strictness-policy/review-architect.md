# Review: RFC-0002 — architect

## Round 2 — 2026-06-12 — reviewed revision 2 — verdict: request-changes

*Advisory delta review (ADR-0004): informs the maestro's synthesis; not a vote; no RFC-body edits.*

**Bottom line.** All four Round 1 blockers are **RESOLVED** — the split premise ([README.md#L42](docs/rfcs/0002-risk-based-strictness-policy/README.md#L42)), the re-ranked native-first ladder + hooks row ([#L170](docs/rfcs/0002-risk-based-strictness-policy/README.md#L170)), the corrected emission matrix ([#L163](docs/rfcs/0002-risk-based-strictness-policy/README.md#L163)), and the taxonomy patches ([#L107](docs/rfcs/0002-risk-based-strictness-policy/README.md#L107), [#L132](docs/rfcs/0002-risk-based-strictness-policy/README.md#L132), [#L150](docs/rfcs/0002-risk-based-strictness-policy/README.md#L150)) all landed cleanly and the reframe introduced **no** contradiction with the "advisory backstop" language. I'm holding at request-changes for **one new, narrow seam** the overlay reframe surfaced: as written, narrator — "the only external publisher" — is denied the R2 transport that publishing requires. This is a one-to-two-sentence clarification, not a redesign; everything else is approvable.

### Round 1 blocker status

| Round 1 blocker | Status | Evidence |
|---|---|---|
| 1. Split "process can't intercept" / "emitted config can" | **RESOLVED** | [#L42](docs/rfcs/0002-risk-based-strictness-policy/README.md#L42)–L52 "split correctly"; degradation reframed as labelled backstop, consistent everywhere |
| 2. Native hooks/permission-deny first-class + re-rank ladder + VS Code Preview caveat | **RESOLVED** | matrix `deterministic pre-action hook` row + ladder `native-deny → native-ask → prose backstop` ([#L170](docs/rfcs/0002-risk-based-strictness-policy/README.md#L170)); "VS Code `hooks` are **Preview** … falls back to allowlist + `sandbox` + prose" |
| 3. Correct §4 matrix to verified reality | **RESOLVED** | VS Code `tools:` "**ENFORCED**"; OpenCode `tools` boolean "**DEPRECATED ≥v1.1.1**"; all three per-agent MCP scope = YES ([#L163](docs/rfcs/0002-risk-based-strictness-policy/README.md#L163)–L167) |
| 4. Most-restrictive precedence + network-egress disposition + devops R4 | **RESOLVED** | precedence rule ([#L107](docs/rfcs/0002-risk-based-strictness-policy/README.md#L107)); egress explicitly rejected with per-vector disposition ([#L132](docs/rfcs/0002-risk-based-strictness-policy/README.md#L132)); devops R4 added with rationale ([#L150](docs/rfcs/0002-risk-based-strictness-policy/README.md#L150)) |

### Maintainer-accepted decisions — coherence check

- **D1 R6-overlay** ([#L101](docs/rfcs/0002-risk-based-strictness-policy/README.md#L101), [#L331](docs/rfcs/0002-risk-based-strictness-policy/README.md#L331)) — **coherent at the taxonomy layer**: R0–R5 declared mutually-exclusive, R6 an orthogonal overlay, "exactly one category" explicitly relaxed ([#L332](docs/rfcs/0002-risk-based-strictness-policy/README.md#L332)). Composition direction (strictest-wins) is consistent with `min(level, allowlist)` and most-restrictive-wins — all three rules push monotonically toward stricter, no directional conflict. **But see the new concern below** for the allowlist interaction.
- **Q14 hand-edit + `test_parity`** ([#L313](docs/rfcs/0002-risk-based-strictness-policy/README.md#L313), [#L268](docs/rfcs/0002-risk-based-strictness-policy/README.md#L268)) — **coherent** and correctly grounded in ADR-0002:37 (build-time generation WON'T-DO; statics raw-copied `installer.py:498`). Clean.
- **Q18 one RFC / Q19 next-free ADR** ([#L8](docs/rfcs/0002-risk-based-strictness-policy/README.md#L8)) — **coherent**; de-reservation reflected in frontmatter and Q19 one-liner.
- **Q1–Q20 collapse to one-liners** — **no dangling references.** Spot-checked every Q-cite in the body (Q2/Q3/Q6/Q10/Q11/Q12/Q14/Q15/Q16/Q17/Q20, D1, D3) against the Open-questions list; all resolve. Q10 body "supersedes old Q10" matches its `SUPERSEDED` one-liner.

### New design concern (the one holding the verdict)

**R6-overlay × per-agent allowlist — narrator cannot transport its own publish.** [#L153](docs/rfcs/0002-risk-based-strictness-policy/README.md#L153) calls narrator "the **only** external publisher" with allowlist `R0, R1, R6`. But an outward publish via MCP (Slack post, Jira comment, PR description) is `MCP POST/PATCH` = **R2** by the taxonomy's own R2 examples ([#L118](docs/rfcs/0002-risk-based-strictness-policy/README.md#L118)). narrator **lacks R2**; devops **has R2 but lacks R6** ([#L150](docs/rfcs/0002-risk-based-strictness-policy/README.md#L150)). Under deny-by-default, **no single agent holds both R2 and R6**, so a substantive outward publish is denied for everyone — and the D1 canonical example "a `gh pr comment` is both transport **and** outward content" ([#L102](docs/rfcs/0002-risk-based-strictness-policy/README.md#L102)) frames it as one action by one actor, contradicting the split. This seam is **new** — it's a direct consequence of promoting R6 from a standalone category to an overlay on top of R2 transport.

**DECIDE — pick one and state it (1–2 sentences):**
- (a) The overlay **composes across a narrator→devops handoff** — narrator authors content (R6 applied at authoring, on an R1 local draft), devops ships it (R2 at transport). This mirrors the existing engineer pattern "R2 only via a devops handoff" ([#L148](docs/rfcs/0002-risk-based-strictness-policy/README.md#L148)) and is the cleanest reading — but then reword [#L153](docs/rfcs/0002-risk-based-strictness-policy/README.md#L153) to "only **author** of external content" (devops does transport) and fix the D1 example so it doesn't imply a single-actor `gh pr comment`; **or**
- (b) narrator holds **scoped R2** for outward-content transport only — then add R2 to narrator's allowlist row with the scope qualifier.

Either resolves it; the model is sound once the cross-agent composition boundary is named.

### NITs (non-blocking)

- **`gate (narrator) + ask` is redundant** ([#L120](docs/rfcs/0002-risk-based-strictness-policy/README.md#L120)). `gate` is already defined as "ask **+** required handoff" ([#L104](docs/rfcs/0002-risk-based-strictness-policy/README.md#L104)), so "+ ask" double-counts. Drop it, or if strict R6 means a *second distinct* approval, say what the extra ask gates. (The Round 1 non-blocking suggestion to rename the `gate` *value* — e.g. `checkpoint` — was not taken; this redundancy is a symptom of that same concept/value overload.)
- **Two-lane (D3) not encoded in the table** ([#L124](docs/rfcs/0002-risk-based-strictness-policy/README.md#L124) vs [#L120](docs/rfcs/0002-risk-based-strictness-policy/README.md#L120)). The R6 cell reads flat `gate (narrator)`, but D3 downgrades short-form to `ask`. A literal table-reader gates everything. Note the lane split in the cell (e.g. `ask (short) / gate (substantive)`).
- **`terraform destroy` example placement.** Listed as an R3 example ([#L116](docs/rfcs/0002-risk-based-strictness-policy/README.md#L116)) yet the precedence note resolves it R3∩R5 → R5 ([#L108](docs/rfcs/0002-risk-based-strictness-policy/README.md#L108)). Harmless (R3 and R5 share identical gates at every level), but a careful reader trips. `git push --force` is the load-bearing example and is correct.
- **D2 absent.** Open questions cite D1 and D3 (narrator) but no D2. If D2 was folded/dropped, a one-word note would prevent a "where's D2?" double-take. Pure bookkeeping.

### Remaining DECIDE items (carried, human call — not blocking)

- The Round 1 calibration DECIDEs the maintainer didn't explicitly close remain product calls, not coherence defects: **R4=`deny` at strict?** (still tops out at `gate`), and **strict-mode devops** (every R3/R5 → override, tensions Q11 override-fatigue). Both defensible as-is; flag only so they're consciously accepted.

---

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
