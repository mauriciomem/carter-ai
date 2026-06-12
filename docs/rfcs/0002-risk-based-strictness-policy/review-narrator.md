# Review: RFC-0002 — narrator

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
