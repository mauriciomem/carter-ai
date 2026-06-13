# Review: RFC-0002 — narrator

## Round 3 — 2026-06-12 — reviewed revision 3 — verdict: approve

**Scope:** narrow delta — only my two Round 2 blockers (QB, QC) on the R6 /
redaction seam. Both resolved. Advisory — maestro synthesizes, user decides.

### Blocker disposition

| R2 blocker | Status | Evidence in rev 3 |
|---|---|---|
| **B1 (QB)** — Q16 forced pass + WARN stopped at `strict`; default `guarded` left a hollow `gate(narrator)` | **RESOLVED** | §6 forces the pass at "**`guarded` and `strict`** … R6 MUST force a redaction/narrator pass regardless of `redaction.enabled`" ([README.md:245](README.md#L245)); §5 WARN now fires on "the `redaction.enabled: false` contradiction at `guarded` or `strict`" ([README.md:225](README.md#L225)) — both halves extended off strict-only |
| **B2 (QC)** — short-form R6 was a bare `ask`, zero redaction logic | **RESOLVED** | short-form = "**`ask` + an inline redaction check** … the agent still runs the redaction-category scan on the short-form content before the ask" ([README.md:128](README.md#L128)); substantive keeps full `gate(narrator)` ([README.md:129-132](README.md#L129-L132)) |

### "Redaction on every outward path" — holds

- `guarded`/`strict`: forced narrator pass (substantive) or inline category scan
  (short-form) — no outward path skips redaction ([README.md:128-132](README.md#L128-L132), [README.md:245](README.md#L245)).
- `loose`: R6 = `allow*` with the **advisory** skepticism nudge, explicitly "loose
  stays advisory" ([README.md:245](README.md#L245)). This is an **honest, labeled
  posture**, not a silent leak — loose's whole contract is advisory. Confirmed
  intended.

### Round 2 non-blocking items — rev 3 delta

- **Commit-messages overlay** (was PARTIAL, accepted as labeled): unchanged —
  still the honesty note "the redaction path is offered, not silently skipped"
  ([README.md:133-136](README.md#L133-L136)). Carter can't gate the server-side
  squash; labeled-and-sufficient as I accepted in R2. Not a default-config leak.
- **G1 — dedicated R6-degradation honesty WARN** (was UNRESOLVED): still folded into
  the generic Q15 hard ack ([README.md:218-224](README.md#L218-L224)); no R6-specific
  "advisory-only on this target" line added. Remains a target-capability honesty
  gap (e.g. VS Code prose backstop), **not** a default-config content leak — the
  redaction logic still ships as agent-body prose, only platform-enforcement
  degrades. Non-blocking, consistent with my R2 disposition.

### Verdict

Both leakage paths on the default (`guarded`) config are closed. No new
default-config leak introduced by rev 3. **approve.** I do not reopen the
R2↔R6 overlay (architect's domain) or G1 (honesty-label nit, not a leak).

### DECIDE
- **none** (blocking). G1 stays an optional honesty-polish item for the architect
  if desired; it does not gate approval.

---

## Round 2 — 2026-06-12 — reviewed revision 2 — verdict: request-changes

**Scope unchanged:** R6 / redaction seam only (external-publish + Q16). Advisory —
maestro synthesizes, user decides.

**Delta summary.** Strong progress: the two structural highs are fully resolved —
R2↔R6 is now a content **overlay** (most-restrictive-wins), killing the
"exactly one category" collision, and the D3 two-lane split lands. But the Q16 fix
stopped at `strict`, leaving the **default `guarded` level** with a hollow
`gate(narrator)` and no WARN when `redaction.enabled: false`; and the new short-form
lane is a **bare `ask`** with zero redaction logic. Two leakage paths remain on the
*default* config — hence request-changes, narrowly scoped to those.

### Round 1 findings — disposition

| R1 finding | Sev | Status | Evidence in rev 2 |
|---|---|---|---|
| §1 R2↔R6 collision (exactly-one-category) | high | **RESOLVED** | overlay [README.md:100-101](README.md#L100-L101); precedence [README.md:107-110](README.md#L107-L110); D1 trail [README.md:330](README.md#L330) |
| §1 commit messages ship outward, no R6 pass | high | **PARTIAL** | honesty note [README.md:128-131](README.md#L128-L131) — labeled, but advisory with no firing trigger |
| §2 sole-publisher handoff fatigue | medium | **RESOLVED** (lane exists; see new B2) | two-lane [README.md:124-127](README.md#L124-L127) |
| §3 Q16 "else ask" leak | high | **PARTIAL** | strict override + WARN [README.md:221-226](README.md#L221-L226), [README.md:207](README.md#L207) — **guarded still leaks** |
| §4 "gate(narrator)" under-specified | low | **RESOLVED** | "redaction pass" language [README.md:124-127](README.md#L124-L127), §6 [README.md:221-226](README.md#L221-L226) |
| §5 R6-degradation honesty WARN | medium | **UNRESOLVED** | only generic Q15 ack [README.md:204-206](README.md#L204-L206) + Q16 WARN; no dedicated R6-advisory label |

### Remaining blockers (request-changes)

**B1 [high, leakage] — Q16 override stops at `strict`; the default `guarded` still leaks.**
- §6 forces the pass "**At `strict`**" only ([README.md:221-226](README.md#L221-L226)); the WARN fires only on "**`strict`** + `redaction.enabled: false`" ([README.md:207](README.md#L207)).
- At `guarded` — the **recommended default for new installs** ([README.md:89](README.md#L89)) — substantive R6 = `gate(narrator)`, but the narrator's entire `<redaction_rules>` block is compiled out by `{% if config.redaction.enabled %}` ([carter-narrator.md.j2:67-111](templates/agents/carter-narrator.md.j2#L67-L111), the RFC's own anchor at [README.md:221-224](README.md#L221-L224)). So `guarded` + `redaction.enabled: false` = handoff to a **rules-less narrator** = generic confirm, **zero redaction logic, no WARN**. My R1 §3 ask was explicitly "strict (**and ideally guarded**) … WARN on level ∈ {guarded,strict}" — rev 2 took only the strict half.
- **Fix:** extend the forced pass **and** the `carter check` WARN to `guarded`; `gate(narrator)` must never route to a narrator whose rules are compiled out (decouple rules-loading from `redaction.enabled` whenever any R6 gate is active). Template-guard change is engineer's call — I flag the requirement, not the implementation.

**B2 [medium-high, leakage] — short-form R6 lane is a bare `ask`, even with redaction enabled.**
- Two-lane sets short-form = `ask` ([README.md:124-125](README.md#L124-L125)). A bare `ask` carries **no redaction logic**: risk is content-borne, but the lane is classified by *form* (one-liner), so a one-line PR comment with a secret gets a generic "yes" and ships. Same zero-logic hole as old Q16, reintroduced by the split.
- My R1 §2 rec was "`ask` **+ inline redaction-rule check** (no full handoff)"; rev 2 adopted the lane but **dropped the inline check**.
- **Fix:** short-form R6 = `ask` **+ inline redaction-rule check**, not bare `ask`.

### Carry-over gap (re-raised, non-blocking)

**G1 [medium, UNRESOLVED] — no dedicated R6-degradation honesty WARN.** Where a target
can't natively enforce the R6 gate (VS Code: no declarative gate, hooks Preview —
[README.md:164](README.md#L164)), "outward content is NOT guaranteed redaction-checked"
still folds into the generic Q15 level ack ([README.md:204-206](README.md#L204-L206)).
Rev 2 added the Q16 (redaction-*disabled*) WARN but not the degraded-on-*target* label.
Recommend a dedicated R6 honesty line so the highest-consequence seam doesn't hide
inside the general notice.

### DECIDE (human calls)
- **DECIDE-1 (B1):** does `guarded` (the default) get the same forced-pass + WARN as
  `strict`, or is a hollow `gate(narrator)` on the default level an acceptable opt-out?
  My advice: **extend to guarded** — leakage parity must not depend on level.
- **DECIDE-2 (B2):** short-form R6 = bare `ask` (max speed) vs `ask + inline redaction
  check` (leak-safe)? My advice: **inline check** — fatigue relief shouldn't cost the
  redaction guarantee.
- **DECIDE-3 (commit msgs):** accept the advisory/"offered" R6 overlay on commit
  messages (no firing trigger; Carter can't gate the server-side squash) as
  labeled-and-sufficient, or add an R6-overlay nudge on the commit path so it actually
  fires? My advice: **accept as labeled** for now — the honesty note clears my R1 blocker.

### New issues introduced by rev 2
- Only B2 (short-form bare `ask`) is genuinely *new* — the two-lane split created a
  low-redaction lane that didn't exist in rev 1. No other new external-content gaps.

---

## Round 1 — 2026-06-11 — reviewed revision 1 — verdict: request-changes

**Scope:** strictly the external-publish / redaction seam (R6 + Q16). I do not
opine on general design, code, installer, or token issues — other agents own those.

**Summary.** The R6 intent is right and naming the narrator as the external-publish
gate matches my role. But three things block as-is: (1) R6 is defined by *content
surface* while R2 is defined by *transport*, and they collide on the same actions,
violating the RFC's own "exactly one category" rule ([README.md:95](README.md#L95));
(2) the Q16 "else `ask`" branch is a genuine leak footgun — verified that disabling
redaction strips the narrator's redaction rules entirely; (3) "strict" can end up
*weaker* on the leak seam than guarded, which contradicts the honesty principle.

---

### 1. R6 category scoping — incomplete + collides with R2 (severity: high)

- R6 is scoped to "outward content (Slack, PR description, release notes, Jira
  comment)" ([README.md:101](README.md#L101)). Missing outward surfaces:
  **git commit messages** (become public on push; this workspace squash-merges, so
  the commit body *is* the public record), **GitHub Discussions / wiki edits**, and
  **npm/pypi release descriptions**.
- **Commit-message gap is the sharp one:** `git commit` is classified R1 = `allow`
  at every level ([README.md:99](README.md#L99)). A secret or internal hostname
  pasted into a commit message ships outward with **no R6 pass at all**, because the
  commit itself is local-write. R6 must cover commit-message *content*, not just
  chat/PR bodies.
- **R2 ↔ R6 collision:** R2 already enumerates "PR/issue create·merge·**comment**"
  and "release publish" ([README.md:100](README.md#L100)), while R6 claims "PR
  description / release notes / Jira comment" ([README.md:101](README.md#L101)). The
  taxonomy mandates each action map to *exactly one* category
  ([README.md:95](README.md#L95)) — but `gh pr comment` is simultaneously a
  remote-write **and** external-publish. The model can't hold. **DECIDE:** either R6
  is a *content overlay* that composes with R2 (an outward action triggers both the
  transport gate and a redaction pass), or split cleanly (R2 = transport mechanics,
  R6 = the human-readable payload). Recommend the overlay framing — it's the only one
  that keeps redaction on every outward path.

### 2. Narrator as sole external publisher — right role, bottleneck risk (severity: medium)

- The allowlist gives only narrator R6 ([README.md:118](README.md#L118)). Correct in
  principle — redaction is my domain. But `gate(narrator)` for *all* outward content
  at guarded ([README.md:101](README.md#L101)) means a one-line PR comment needs a
  full handoff. That's handoff fatigue, and fatigued users disable the policy — the
  exact failure the RFC warns about ([README.md:198-199](README.md#L198)).
- **Recommendation / DECIDE:** add a lightweight lane for short-form low-risk R6 —
  e.g. guarded = `ask` + inline redaction-rule check (no full agent handoff),
  reserving the full narrator handoff for `strict` or for content over a size/target
  threshold. Keeps the leak guarantee without serializing every one-liner.

### 3. Q16 — "else `ask`" is a leak footgun (severity: high — content leakage) — **DECIDE**

This is my most important call.

- RFC rec: "R6 requires a narrator handoff only when `redaction.enabled`; else `ask`"
  ([README.md:255-256](README.md#L255-L256)).
- **Verified:** the narrator's entire `<redaction_rules>` block is wrapped in
  `{% if config.redaction.enabled %}`
  ([carter-narrator.md.j2:67-111](templates/agents/carter-narrator.md.j2#L67-L111)).
  So `redaction.enabled: false` doesn't just skip a pass — it ships a narrator with
  **no redaction rules loaded at all**.
- Net effect of the "else `ask`" branch: outward content gets a *generic* human
  confirmation with **zero** redaction logic in scope. All 7 default categories
  (secrets, internal_urls, security_incidents, pii, financials, employee_data,
  infra_ids — [config.py defaults, per task context]) can flow to public channels on
  a single "yes."
- **The contradiction:** a user at `level: strict` who set `redaction.enabled: false`
  gets `ask`-only on the leak seam — i.e. **strict is weaker than guarded here**.
  Strictness must never *decrease* protection on the highest-consequence path.
- **Recommendation:** decouple *who gates* from *what they check*. `redaction.enabled`
  should at most narrow the category list — it must not remove the R6 handoff. At
  minimum: `strict` (and ideally `guarded`) MUST force a narrator/redaction pass even
  when `redaction.enabled: false`, and `carter check` MUST emit a loud WARN on the
  `level ∈ {guarded,strict}` + `redaction.enabled: false` contradiction. **DECIDE:**
  is "disable redaction → outward content gets only a generic ask" an acceptable
  opt-out, or must strict override it? My advice: strict overrides.

### 4. Gate vocabulary — "gate(narrator)" is under-specified (severity: low)

- `gate` is defined as "ask **+** required handoff to the owning agent / checkpoint
  artifact" ([README.md:84-86](README.md#L84-L86)) — internally consistent, and for
  R6 the owning agent is correctly the narrator.
- But the table cell "gate (narrator)" ([README.md:101](README.md#L101)) doesn't say
  the handoff *includes a redaction pass*, nor does it distinguish two cases: (a)
  narrator **authored** the content, vs (b) another agent authored outward content
  and narrator must **redaction-review** it. Both must trigger the pass; today the
  wording reads like "narrator confirms," which conflates human-confirm with
  redaction-specialist routing.
- **Recommendation (wording):** define R6's gate explicitly as *"route content
  through narrator for a redaction pass + human confirm before publish — regardless
  of which agent drafted it."*

### 5. Honesty / labeling — redaction degradation needs its own WARN (severity: medium)

- The RFC commits to honest labeling where enforcement degrades to prose
  ([README.md:27-31](README.md#L27-L31)) and has a generic degradation WARN via
  `carter check` (Q15, [README.md:249](README.md#L249)).
- The emission table shows VS Code / Copilot may be advisory-only
  ([README.md:130-135](README.md#L130-L135)). For R6 that means outward content on
  those targets is **not guaranteed redaction-checked** — but there's no R6-specific
  honesty label; it folds into the generic level WARN.
- **Recommendation:** because redaction is the highest-consequence leak seam, give it
  a dedicated WARN — e.g. *"R6/redaction is advisory-only on this target; outward
  content is NOT guaranteed redaction-checked."* Don't let the one guarantee a user
  most needs to trust hide inside a general degradation notice.

---

### DECIDE items (for maestro synthesis → revision 2)

- **[D1 — high]** R2↔R6 collision: overlay (compose) vs split. Recommend overlay so
  redaction stays on every outward path (§1).
- **[D2 — high, leakage]** Q16 "else ask": acceptable opt-out vs strict must force a
  redaction pass even when `redaction.enabled: false`. Recommend strict overrides;
  add `carter check` WARN on the contradiction (§3).
- **[D3 — medium]** Lightweight lane for short-form R6 to avoid handoff fatigue (§2).

### Non-blocking nits

- Add commit messages, Discussions/wiki, and package release descriptions to the R6
  examples list ([README.md:101](README.md#L101)) (§1).
- Tighten the "gate (narrator)" wording to name the redaction pass explicitly (§4).
