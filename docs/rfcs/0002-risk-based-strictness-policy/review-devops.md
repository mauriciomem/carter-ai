# Review: RFC-0002 — devops

## Round 2 — 2026-06-12 — reviewed revision 2 — verdict: approve

**Summary.** All four Round 1 blockers (B1–B4) are resolved with correct `file:line` grounding, and the emission seam is now right end-to-end: per-agent MCP scope lives in agent frontmatter, `configure_mcp_servers` is explicitly left global-only, and `copilot mcp add` is acknowledged as inherently global ([README#L191-L194](docs/rfcs/0002-risk-based-strictness-policy/README.md#L191-L194)). A fresh-session implementer is now pointed at the correct code (agent emission, not the server registry). Remaining items are non-blocking polish — no infra change here is wrong as written.

### Blocker resolution (delta)

- **B1 — Q14 "bake at build time" → RESOLVED.** Rev 2 reframes exactly as requested: build-time generation is called **WON'T-DO per ADR-0002:37** (verified: WON'T-DO row), statics **raw-copied at `installer.py:498`** (verified: `install_agents` → `_install_file` → `shutil.copy2`), defaults now **hand-edited into static `agents/*.md`** kept honest by a **`test_parity.py` extension (dual-source hand-edit, *not* generation)** ([README#L269-L272](docs/rfcs/0002-risk-based-strictness-policy/README.md#L269-L272), [README#L312-L316](docs/rfcs/0002-risk-based-strictness-policy/README.md#L312-L316)). Implementable — `test_parity.py` already guards frontmatter byte-parity (ADR-0002 Current Status), so extending it to the new keys is a known pattern, not a new mechanism.

- **B2 — MCP scoping seam → RESOLVED.** §4 now states per-agent MCP scope is emitted "in **agent frontmatter**, *not* the global `configure_mcp_servers` @ `installer.py:782`" and that "`copilot mcp add` is inherently global" ([README#L191-L194](docs/rfcs/0002-risk-based-strictness-policy/README.md#L191-L194)). P2 relocated the work to "per-agent MCP scope in frontmatter" ([README#L235-L238](docs/rfcs/0002-risk-based-strictness-policy/README.md#L235-L238)). The wrong-seam instruction from rev 1 is gone.

- **B3 — Deprecated OpenCode mechanism → RESOLVED.** Matrix marks `tools` boolean **DEPRECATED ≥v1.1.1** ([README#L163](docs/rfcs/0002-risk-based-strictness-policy/README.md#L163)); emission rule says "emit **`permission`** (not the deprecated `tools` boolean)" ([README#L176](docs/rfcs/0002-risk-based-strictness-policy/README.md#L176)). Correct.

- **B4 — "read-only" relabel in scope → RESOLVED.** Relabel is now a **P1 MUST** — "drop the 'read-only' prose (Q3 P1 MUST)" ([README#L233-L234](docs/rfcs/0002-risk-based-strictness-policy/README.md#L233-L234)) — anchored to the false guarantee at `installer.py:271` (verified: shared full-scope `REQUIRED_ENV_VARS`), with tool-name denial riding the P2 frontmatter emission ([README#L191-L195](docs/rfcs/0002-risk-based-strictness-policy/README.md#L191-L195)). The P1(relabel)/P2(denial) split is sound: dropping false prose is a no-behavior docs change (fits P1); emitting `permission: deny` is enforcement (fits P2). The security-lie is no longer shipped or deferred.

### Round 1 DECIDE items

- **D2 (Q15 hard ack) → LANDED.** §5 and Q15 both require an explicit acknowledgement at install **and** `carter check`, "not a soft WARN" ([README#L204-L206](docs/rfcs/0002-risk-based-strictness-policy/README.md#L204-L206), [README#L317-L318](docs/rfcs/0002-risk-based-strictness-policy/README.md#L317-L318)). Resolved as recommended.
- **D3 (Q20 `max`) → LANDED.** Effective gate = `max(workspace level, plan push_policy)`, `manual` only *tightens* R2 ([README#L274-L276](docs/rfcs/0002-risk-based-strictness-policy/README.md#L274-L276), [README#L327-L329](docs/rfcs/0002-risk-based-strictness-policy/README.md#L327-L329)). Correct one-directional override.
- **D4 (Q2 table) → LANDED.** Matrix now reflects the corrected reality: VS Code `tools:` **ENFORCED**, Copilot `hooks` preToolUse can **BLOCK**, all three do per-agent MCP scope ([README#L162-L168](docs/rfcs/0002-risk-based-strictness-policy/README.md#L162-L168)).
- **D5 (de-dup server triple) → still open, non-blocking.** The hardcoded `["github","terraform","atlassian"]` is still duplicated across install (`installer.py:782` region) and uninstall (`installer.py` ~948, verified literal triple). Rev 2 doesn't lift it to a constant — fine, it's independent of this RFC, but worth folding into the P2 implementation while that file is open.

### Remaining non-blocking items (carry into the plan, not approval blockers)

- **N1 — Q14 vs Trade-offs inconsistency (nit).** Trade-offs commits to option (a) "hand-edited into the static `agents/*.md`" ([README#L269-L271](docs/rfcs/0002-risk-based-strictness-policy/README.md#L269-L271)), while Q14 still lists "(a) … — or a global policy file read at install" ([README#L315-L316](docs/rfcs/0002-risk-based-strictness-policy/README.md#L315-L316)). Minor ambiguity for the implementer. **DECIDE:** drop the "or global policy file" alternative from Q14 to match the Trade-offs commitment, or explicitly defer the (a)/(b) choice to the execution plan. Not blocking.
- **N2 — `--mcp`-decoupled lint false-positive (P3 design note).** Agent files install always but server defs only with `--mcp`; agents will carry `carter-*_*: deny` referencing servers that may be unwired. Harmless at runtime (denying an absent tool), but the §5 lint must **not** WARN "server not wired" when the user simply omitted `--mcp`. Rev 2 §5 ([README#L200-L210](docs/rfcs/0002-risk-based-strictness-policy/README.md#L200-L210)) doesn't note this interaction — capture it as a P3 lint requirement.
- **N3 — relabel touches both sources (parity caveat).** `test_parity.py` checks **frontmatter** parity, but "read-only" lives in the agent **body** (`<mcp>` section). Dropping it from static `agents/*.md` won't be caught by parity if the template body diverges — P1 must edit both static and template bodies for consistency. One-line implementer note.

No new infra/install defect introduced by the revision.

---

## Round 1 — 2026-06-11 — reviewed revision 1 — verdict: request-changes

**Summary.** The model is sound and the honest "scaffolder-not-a-runtime" framing is correct — emit platform-native config + lint, degrade to labelled prose elsewhere. But two load-bearing *installer* claims are wrong as written and will send a fresh-session implementer to the wrong code: (1) the Q14 "bake defaults **at build time**" recommendation rests on a mechanism that was explicitly abandoned (ADR-0002 Phase 2 = **WON'T DO**), and (2) P2's "`configure_mcp_servers` gains per-agent scoping" puts the work in the wrong function — per-agent MCP scope lives in *agent frontmatter*, not in `configure_mcp_servers`. Both are correctable framing/seam fixes, not fatal flaws — hence request-changes, not reject.

---

## 1. `configure_mcp_servers` rewrite — blast radius & feasibility (focus 1)

Verified the function and the flow:

- Hardcoded triple `servers = ["github", "terraform", "atlassian"]` at [carter/installer.py](carter/installer.py#L786); flat-merged into VS Code `mcp.servers` via `_merge_json_key`, into `copilot mcp add`, and into opencode `mcp`. No agent dimension. Matches the RFC's problem table.
- Uninstall repeats the literal triple at [carter/installer.py](carter/installer.py#L948) — confirmed drift risk.
- `configure_mcp_servers` is gated behind `--mcp` at [carter/installer.py](carter/installer.py#L1115); `install_agents` is **not** ([carter/installer.py](carter/installer.py#L1106)).

**Correction (request-changes).** P2 says "`configure_mcp_servers` gains per-agent scoping where supported." That is the wrong seam. `configure_mcp_servers` only writes **global server *definitions***. Per-agent *scoping* is a property of each agent, and on every target it is emitted into the **agent file**, not the server registry:
- OpenCode → `permission` / tool-name patterns (`carter-github_*: deny`) in agent frontmatter.
- VS Code → `tools: [carter-github/*]` allowlist (+ `mcp-servers`) in agent frontmatter.
- Copilot CLI → `mcp-servers` per agent **profile** — and per the verified matrix `copilot mcp add` is *inherently global*, so scoping there **cannot** come from `configure_mcp_servers` at all.

So the real blast radius is: `configure_mcp_servers` itself changes **little** (it keeps wiring global defs; at most it stops hardcoding the list), while the per-agent work lands in agent emission (`install_agents` + templates). The RFC should relocate the P2 bullet accordingly, or a fresh-session implementer will edit the wrong function. **DECIDE:** explicitly state that Copilot/VS Code per-agent MCP scope is emitted in agent frontmatter, and `configure_mcp_servers` stays global-only.

**Easy win, independent of this RFC:** lift the triple to one module-level constant consumed by both install ([L786](carter/installer.py#L786)) and uninstall ([L948](carter/installer.py#L948)). Per-agent or not, the duplicated literal is a latent drift bug.

**`--mcp` decoupling (request-changes, minor).** Because agent files install always but server defs only with `--mcp`, agents will carry `carter-*_*: deny` permissions referencing servers that may not be wired. That is *harmless* (denying an absent tool), but the §5 lint must not WARN "server not wired" when the user simply omitted `--mcp`. The RFC's lint scope doesn't mention this interaction — add it.

## 2. Per-target enforcement (Q2 — DECIDE)

The verified 2026 matrix resolves the RFC's three "verify (Q2)" hedges to **YES on all three targets** for per-agent MCP scoping. The RFC under-claims:

- **VS Code** `tools:` is an *enforced* allowlist (the RFC's emission table calls it "list-only / verify"). Upgrade the claim: VS Code enforces the per-agent tool allowlist and supports `mcp-servers` + `sandbox` (fs/network) + Preview `hooks`.
- **Copilot CLI** has `tools:` in profile, `mcp-servers` per profile, and `hooks` `preToolUse` — the **strongest deterministic gate** of the three. The RFC marks Copilot per-action gate as "verify"; it should record `hooks` as the enforcing mechanism (Preview, but real).

**Recommended per-target emission shape** (to replace the hedged §4 table):

| target | tool allowlist | per-action gate | MCP scope |
|---|---|---|---|
| OpenCode | `permission` (`tools:` bool DEPRECATED ≥v1.1.1 — **do not emit `tools:` booleans**) | `permission` allow/ask/deny + bash globs | tool-name patterns `carter-x_*: deny` |
| VS Code | `tools:` enforced allowlist | none declarative → `sandbox` + Preview `hooks` + prose | `tools:[carter-x/*]` / `mcp-servers` |
| Copilot CLI | `tools:` in profile | `hooks` `preToolUse` (deterministic) | `mcp-servers` per profile |

**DECIDE flag for P2:** OpenCode's `tools:` boolean form is deprecated — the RFC's §4 "OpenCode: `tools: {name: bool}`" is the deprecated path. Emit `permission` instead. This is a concrete coding instruction the RFC currently gets wrong.

## 3. Global vs workspace install + Q14 baked defaults — **premise falsified (request-changes)**

This is the most important finding. Q14 recommends "bake `guarded` defaults into the static `agents/*.md` **at build time**." **There is no build-time generation.** ADR-0002 Phase 2 (build-time generation + drift check) is **WON'T DO** — "premise falsified — static and template are different agent *designs*, not the same content" ([docs/adr/0002-single-source-agent-generation.md](docs/adr/0002-single-source-agent-generation.md#L36)).

Verified mechanics:
- `install_agents` **raw-copies** static `agents/carter-*.md` globally via `_install_file` — no carter.yaml, no rendering ([carter/installer.py](carter/installer.py#L498)).
- Workspace agents render from carter.yaml through `scaffold.render_agents` ([carter/scaffold.py](carter/scaffold.py#L111)) — a *separate* source (`templates/agents/*.j2`).
- Static frontmatter and template frontmatter are kept in **byte-parity** by `tests/test_parity.py` (ADR-0002 status table), not generated one from the other.

So "bake at build time" actually means: **hand-edit 7 static `agents/*.md` AND 7 `templates/*.j2`, keep their frontmatter byte-identical for the default render, and extend `test_parity.py` to cover the new `tools`/`permission`/`<policy>` keys.** That is a real, recurring dual-source maintenance cost the RFC currently hides behind a non-existent build step.

**Recommendation / DECIDE:**
- **Reframe Q14**: drop "at build time." Either (a) bake a `guarded` default into the static agents *as authored content* (+ parity test extension), accepting dual-source sync, or (b) introduce a small global policy file read by `install_agents` at copy time so global agents resolve policy from one source instead of frozen literals. I lean (a) for global (zero new runtime, parity test already guards drift) — but the RFC must own the manual-sync cost honestly, exactly as ADR-0002 learned.
- **State the resolution split explicitly:** Q12's "policy lives in carter.yaml, agents always re-emitted from it" holds **only for workspace** agents. **Global** installs have no carter.yaml in scope ([install_agents](carter/installer.py#L498)) — their only knob is the baked static default (or option b). `carter update` re-copies static (baked default re-applied, hand-edits wiped — acceptable, since policy isn't hand-edited) and re-renders workspace from carter.yaml. The RFC conflates these two paths.

## 4. Multi-target consistency WARN (Q15) — sufficient? where? (DECIDE)

WARN is the right instinct and there is precedent to reuse, **not** reinvent: `config_warnings` already warns on init/update/check for the narrator/redaction edge case (ADR-0002 status table). Route the degradation WARN through the same path.

- **Where it fires:** two points — (a) at agent/MCP emission time for a target that can't enforce the declared level (install flow [L1106–L1115](carter/installer.py#L1106)), and (b) in `carter check` for drift. Both, not one.
- **Sufficiency — DECIDE:** a WARN is fine for `guarded`. For `strict` on a target with **no declarative per-action gate** (VS Code per the matrix; Copilot only via Preview `hooks`), R3/R5 `deny` silently degrades to prose — a user asking for `strict` gets advisory-only and may not read the WARN. Recommend: WARN at `guarded`, but at `strict` on a non-enforcing target require an explicit acknowledgement (config flag or `carter check` error) rather than a soft WARN. Silent `strict`→prose is the failure mode that erodes trust in the whole feature.

## 5. `push_policy` reconciliation (Q20 — DECIDE)

`push_policy: manual|auto` is **plan-scoped** ([docs/reference/frontmatter.md](docs/reference/frontmatter.md#L25)); `policy.level` is workspace/agent-scoped. Folding `manual ⇒ R2=gate` is sound **only as a tightening**, and the RFC doesn't state the precedence rule:

- **Effective R2 gate = max(workspace level gate, plan push_policy gate).** A plan's `push_policy` may **raise** R2 (e.g. `ask`→`gate`) but must **never lower** it — a `strict` workspace with `push_policy: auto` must not drop R2 below `gate`. Without this rule you do get two conflicting sources of truth; with it, push_policy is a clean per-plan override in one direction.
- **Honesty caveat:** push_policy lives in plan frontmatter that Carter reads as *prose to the agent*, not a runtime gate. So this reconciliation is advisory-layered-on-advisory unless the platform-native R2 gate (OpenCode `permission`, Copilot `hooks`) is what actually stops the push. Document that the plan field *informs* the gate; the gate *is* the enforcement. Keep the field, add the `max()` precedence sentence to `frontmatter.md`.

## 6. Token / MCP model from the infra angle (Q3)

Verified: `REQUIRED_ENV_VARS` = one full-scope token per service ([carter/installer.py](carter/installer.py#L271)), injected as `${GITHUB_TOKEN}` etc. into all three targets' MCP defs (e.g. [mcp/copilot/github.json](mcp/copilot/github.json#L1), [mcp/opencode/github.json](mcp/opencode/github.json#L1)). The "read-only" prose is therefore fiction — confirmed in the static agents: engineer terraform "Read-only" ([agents/carter-engineer.md](agents/carter-engineer.md#L43)), architect "read-only access" ([agents/carter-architect.md](agents/carter-architect.md#L39)), pm github "Read-only" ([agents/carter-pm.md](agents/carter-pm.md#L42)) — the shared token can write regardless.

**Operationally realistic call.** Per-agent scoped tokens (fine-grained GitHub PATs / TFC team tokens per agent) are a genuine ops burden: token sprawl, rotation, secret-store wiring, and 7 agents × N services of credentials. Deferring them is the right trade. The Q3 rec — **deny write tool-names where supported + drop "read-only" wording where unenforceable** — is cheap and is enforceable on all three targets per the matrix, so it should land in P2, not be deferred. The relabel is **non-negotiable**: shipping "read-only" prose over a full-scope token is a false security guarantee. Q3's "DECIDE: accept residual risk vs scoped tokens" should resolve to *tool-name denial now, scoped tokens later (separate RFC)*.

---

## Blocking concerns (request-changes)

- **B1 — Q14 premise is falsified.** "Bake at build time" relies on ADR-0002 Phase 2, which is WON'T DO ([docs/adr/0002…](docs/adr/0002-single-source-agent-generation.md#L36)). Reframe as dual-source hand-edit + `test_parity.py` extension, or a global policy file. Must fix before P2.
- **B2 — P2 puts MCP scoping in the wrong function.** Per-agent MCP scope is emitted in *agent frontmatter*, not `configure_mcp_servers` ([L782](carter/installer.py#L782)); `copilot mcp add` is inherently global. Relocate the P2 bullet or the implementer edits the wrong seam.
- **B3 — Deprecated OpenCode mechanism.** §4 prescribes `tools: {name: bool}`; that boolean form is DEPRECATED (≥v1.1.1). Emit `permission` instead.
- **B4 — "read-only" relabel must be in-scope for P2.** Leaving false "read-only" prose over a full-scope token ([installer.py#L271](carter/installer.py#L271)) ships a security lie; the relabel + tool-name denial is cheap and enforceable now.

## DECIDE items

- **D1 (Q14):** baked static default (+ parity test) **vs** global policy file read at install. Recommend baked default for global; carter.yaml for workspace — state the split explicitly.
- **D2 (Q15):** for `strict` on a non-enforcing target, soft WARN **vs** explicit ack/error. Recommend hard ack — silent `strict`→prose erodes trust.
- **D3 (Q20):** adopt **effective gate = max(workspace, plan push_policy)** so push_policy can only tighten R2, never loosen it; document in `frontmatter.md`.
- **D4 (Q2):** confirm the corrected per-target emission table (§2 above) — VS Code/Copilot enforce more than the RFC claims; Copilot `hooks` is the strongest gate.
- **D5 (drift, non-blocking but do it):** de-duplicate the server triple across [L786](carter/installer.py#L786)/[L948](carter/installer.py#L948) into one constant.
