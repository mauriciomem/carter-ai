# Review: RFC-0002 — engineer

## Round 1 — 2026-06-11 — reviewed revision 1 — verdict: request-changes

*Advisory review (ADR-0004): informs the maestro; does not vote or bind. Focus: code/test feasibility + security.*

**Summary.** This is an unusually honest, well-grounded RFC — the "scaffolder, not a runtime" framing is correct and the phasing is sound. It is feasible to build on the existing seams (`_deep_merge`, `config_warnings`, `carter check`, the `carter-ops audit` path). It is *not* yet ready to code: the escape hatch conflates *logging* with *authorization*, the "drop read-only wording" honesty fix is filed as a recommendation when it must be a P1 hard requirement, the bash-invoked write path is missing from the enforcement model, and config validation + per-target template rendering are under-specified.

---

## 1. Code feasibility

### Config `policy` block — mostly clean, one real footgun

- **Additive merge works.** `DEFAULT_CONFIG` ([carter/config.py](carter/config.py#L17)) has no `policy` key; adding one is backward-compatible. `_deep_merge` ([carter/config.py](carter/config.py#L134)) recurses dicts and preserves extra keys, so `level`/`unknown_tool`/`audit_overrides` (scalars) and `overrides: {}` (dict) all merge correctly. A user setting `overrides: {remote-write: deny}` recurses cleanly against the empty-dict default. ✓
- **List-replace footgun is real for two structures.** `_deep_merge` *replaces* lists wholesale ([carter/config.py](carter/config.py#L138-L146)). The RFC's "user-extensible" framing (Q9, ~[README.md](docs/rfcs/0002-risk-based-strictness-policy/README.md#L313)) is **additive in intent but replace in practice** for:
  - the **per-agent allowlist** (§3 ~[README.md](docs/rfcs/0002-risk-based-strictness-policy/README.md#L128)) — values are lists (`engineer: [R0, R1]`). A user who wants to add `R2` must restate the *entire* list; they cannot append. If the allowlist ships in `DEFAULT_CONFIG`, a partial user override silently drops shipped categories.
  - the **tool→risk map** (Q9) — only safe from the footgun if shipped as a `dict` of `{tool_name: category}` (per-key merge). If shipped as a *list* of mapping entries, any user addition wipes the shipped map.
  - **Action:** the RFC should (a) mandate dict shapes for every user-extensible structure, and (b) explicitly document that list-valued policy keys are replace-not-append, or add a custom merge for `policy`. Currently the config fence (~[README.md](docs/rfcs/0002-risk-based-strictness-policy/README.md#L88)) only shows scalars + `overrides: {}` and never shows the allowlist/map shape — that gap is where the footgun hides. **(feasibility — blocking until shapes are pinned)**
- **No schema validation specified.** `load_config` validates only `agent_suffix` ([carter/config.py](carter/config.py#L88) pattern). Nothing would reject `level: guared` or an invalid gate value — it would silently degrade. P1 must add validation mirroring `_validate_agent_suffix` (raise `ConfigError` on bad `level`/gate/category). The RFC doesn't mention this. **(feasibility — should-fix)**

### Per-target frontmatter emission — bigger lift than "add frontmatter"

- `base_agent.md.j2` ([templates/base_agent.md.j2](templates/base_agent.md.j2#L4)) emits **one** `{% block frontmatter %}` per agent; children override it with `description`/`mode`/`temperature` only ([templates/agents/carter-engineer.md.j2](templates/agents/carter-engineer.md.j2#L5-L8)).
- **The render→target seam is single-render, multi-target.** `render_agents` ([carter/scaffold.py](carter/scaffold.py#L113)) produces *one* `{filename: content}` dict; the installer copies the same `.md` to whichever target dirs. Emitting **different** frontmatter per target (OpenCode `permission` map vs VS Code/Copilot `tools:` list) therefore requires either target-conditional Jinja keyed on the resolved target, or rendering N times. This is a structural change to `render_agents` + the base template, **not** a trivial frontmatter add. The RFC's §4 should acknowledge this seam explicitly. **(feasibility — should-fix; doable, just under-scoped)**
- **Static global agents have no config in scope** (Q14, ~[README.md](docs/rfcs/0002-risk-based-strictness-policy/README.md#L333)). Baking `guarded` frontmatter into `agents/*.md` at build time is feasible but creates a parity surface (see Testing). The Q14 `DECIDE` is correctly flagged.

### MCP per-agent scoping — feasible only where the platform has the dimension

- `configure_mcp_servers` ([carter/installer.py](carter/installer.py#L782)) is flat: `servers = ["github","terraform","atlassian"]` ([installer.py](carter/installer.py#L791)), merged globally via `_merge_json_key(... "mcp.servers" ...)`. There is **no agent dimension** today.
- VS Code `mcp.servers` is a global settings merge — **per-agent MCP scope is not achievable on VS Code** (matches the Q2 matrix). OpenCode can deny `carter-github_*` tool names per agent. So §4's "per-agent MCP server scope" row is only realizable on OpenCode/Copilot; the RFC says "where supported," which is honest, but the matrix should name VS Code as a hard *no*.

---

## 2. SECURITY — Q3 token blast radius **(DECIDE)** — finding severity: **HIGH (honesty), MEDIUM (residual)**

**Verified:** `REQUIRED_ENV_VARS` ([carter/installer.py](carter/installer.py#L271)) = one full-scope token per service; `mcp/copilot/github.json` and `mcp/opencode/github.json` both wire `"GITHUB_TOKEN": "${GITHUB_TOKEN}"` ([mcp/copilot/github.json](mcp/copilot/github.json#L6), [mcp/opencode/github.json](mcp/opencode/github.json#L6)). The MCP server process is global; agents are prompt personas, not OS principals. Every server invocation runs with the same write-capable token regardless of which agent triggered it.

**Is denying write tool names (token still full-scope) honest defense-in-depth or theater?**
- It is **legitimate defense-in-depth at the model/tool-surface layer** — *provided the "read-only" claim is dropped*. Tool-name denial (OpenCode `permission`, VS Code allowlist omission, Copilot `tools:`/hooks) reduces the dominant failure mode for a scaffolder: *accidental model-driven writes*. That is real value.
- It becomes **theater the moment it is labeled "read-only"**, because that word is a *credential* guarantee the design cannot make. Today the static agents literally say this — "Read-only" ([agents/carter-engineer.md](agents/carter-engineer.md#L43)), "read-only access" ([agents/carter-architect.md](agents/carter-architect.md#L39)), and similar in pm/learner.
- **The RFC's own fix — "drop the 'read-only' wording wherever it cannot be enforced" (§4 MCP rule, ~[README.md](docs/rfcs/0002-risk-based-strictness-policy/README.md#L182)) — is exactly right, but it is filed as a recommendation. It must be a P1 MUST.** Shipping a "security policy" while leaving "read-only" prose in place would *worsen* posture: users would trust a now-policy-blessed guarantee that is weaker than the words imply. **(blocking)**

**Bash is the universal bypass — currently missing from the model. Severity: MEDIUM.**
- R2/R3/R5 (push, PR, `terraform apply`, `rm -rf`) are typically invoked via the **shell/bash tool**, not the MCP server. Denying the MCP write *tool name* does nothing to a `gh pr create` or `terraform apply` run through bash against the same token.
- Real enforcement vectors exist: OpenCode `permission.bash` globs, Copilot CLI `hooks` preToolUse bash-allowlist. VS Code **cannot** declaratively gate bash. §4's emission matrix maps only "tool allow/deny" and "per-action gate" and never names bash-command gating as the vector for shell-invoked R2/R3/R5. Without it, the allowlist denies the MCP path while the bash path stays wide open — that is the line between honest and theater for git/terraform specifically. **(blocking — add bash gating to the enforcement model + mark VS Code unable)**

**Is per-agent scoped tokens correctly deferred?** Yes, defensibly. Scoped tokens are a much larger lift (the installer has no per-agent secret dimension — [installer.py](carter/installer.py#L271)), and the dominant threat for a scaffolder is accidental model action, not token theft. Guarded-default + honest labeling strictly improves on today's unenforced prose. **DECIDE recommendation:** ship guarded-by-default **with the mandatory wording-drop**, file scoped-tokens as a follow-up RFC, and record the residual blast-radius risk in the policy docs. Do **not** let "read-only" survive anywhere past P1.

---

## 3. Trust boundaries — labeled honestly, but the matrix is stale

The emitted config *is* the trust boundary; if the model ignores prose, only platform-native config stops R2/R3.

- **Genuinely enforced:** OpenCode `permission`/`tools` (runtime); Copilot CLI per-profile `tools:`/`mcp-servers` + `hooks` preToolUse (deterministic block); VS Code `tools:` allowlist (unlisted tool is unavailable).
- **Advisory only:** the `<policy>` prose block on every target; the maestro risk table; the handoff protocol (Q10 — model can ignore).
- **Honesty:** §4 ("enforce natively where supported, label the rest"), Q1, and the "Per-target inequality" trade-off label this correctly. ✓
- **Staleness — should-fix:** §4's matrix (~[README.md](docs/rfcs/0002-risk-based-strictness-policy/README.md#L155)) still carries "**verify (Q2)**" placeholders for Copilot CLI and VS Code. Per the now-verified platform matrix, this **understates Copilot CLI** (which has real `hooks` enforcement) and risks implementers treating it as advisory-only. Fill the cells before P2: Copilot CLI = `tools:` + per-profile `mcp-servers` + `hooks` (enforced); VS Code = `tools:` allowlist enforced, **no** declarative per-category ask/deny (interactive confirm + MCP sandbox only).

---

## 4. Escape-hatch audit (Q11) — **conflates logging with authorization (blocking clarification)**

- **Audit path is real and reusable.** `_audit` appends JSONL to `~/.carter/audit.log` ([carter/ops/carter_ops.py](carter/ops/carter_ops.py#L52)); `_handle_audit` ([carter_ops.py](carter/ops/carter_ops.py#L123)) is reachable via `carter-ops audit --operation X --result Y`. Recording an override is trivial. ✓
- **But it is a ledger, not a gate.** The audit is **best-effort** (`except OSError: pass`, [carter_ops.py](carter/ops/carter_ops.py#L59)) and **post-hoc** — a record of what the model *claims* it did. Nothing forces the model to call it before a denied action, and writing a log line **cannot lift a platform-enforced `deny`**. The RFC's "a `deny`-gated action proceeds only with an explicit single-action override recorded via `carter ops` audit" (§6, ~[README.md](docs/rfcs/0002-risk-based-strictness-policy/README.md#L204)) conflates the two.
- **Define the override per enforcement tier:**
  - *Platform-enforced deny* (OpenCode/Copilot) → the only real override is a human action at the platform layer (permission prompt / hook approval) or flipping the gate `deny→ask`; the audit entry is the *record* afterward, not the mechanism.
  - *Advisory deny* (prose) → override = model self-report to audit, explicitly labeled **non-binding** (depends on model compliance).
- **Single-action vs session-wide** is deterministic only at the platform layer (each `ask` is per-invocation by nature on OpenCode/Copilot); at the prose layer it depends on model compliance. Achievable where enforced, advisory where not — consistent with the rest, but say so. **(blocking clarification — don't present the ledger as the gate)**

---

## 5. What `carter check` can ACTUALLY lint (Q13) — scope is honest and testable offline

- **Confirmed feasible.** `check` ([carter/cli.py](carter/cli.py#L183)) already loads config, iterates installed agent files per target, validates plan frontmatter, and emits `config_warnings`. Extensions:
  - emitted-frontmatter ↔ declared-allowlist → parse `.md` YAML frontmatter, diff against config. Feasible.
  - category ↔ gate-per-level → pure function over config; trivially unit-testable offline.
  - `carter.yaml` ↔ installed drift → existence drift already done; content drift has prior art (`_sha256` + manifest in the installer).
  - **degradation WARN** → `config_warnings` ([carter/scaffold.py](carter/scaffold.py#L73)) is the exact existing, tested seam; a "target X cannot enforce level Y" warning slots in cleanly. ✓
- **Cannot verify runtime denial** (Q17) — correct, and §5 / Q13 / Q17 state it out of scope explicitly. Honest boundary. ✓
- **Gap — should-fix:** `carter check` requires `.carter/carter.yaml`; **global installs have none** (Q14), so the lint cannot validate global static agents at all. The RFC notes Q14 but should state plainly that the lint's scope is **workspace-only** and global agents are unverifiable — otherwise users assume full coverage.

---

## 6. Testing (Q17) — sufficient for in-scope, two named gaps

- **Strategy matches existing patterns.** Emission unit tests (policy→frontmatter, policy→MCP entries) slot into [tests/test_scaffold.py](tests/test_scaffold.py) / [tests/test_install.py](tests/test_install.py); lint tests into the `check` surface; prose-block assertions are brittle but acceptable for "the `<policy>` block lists the allowlist." All offline. ✓ (Repo cmd excludes `evals/test_live.py` — keep policy tests in `tests/` + `evals/test_skills.py`/`test_routing.py`.)
- **Gap 1 — config validation tests:** add tests that bad `level`/gate/category values raise `ConfigError` (pairs with §1's missing validation).
- **Gap 2 — parity:** [tests/test_parity.py](tests/test_parity.py) enforces template↔static-agent parity today. Baked `guarded` global frontmatter (Q14) + per-target conditional rendering will complicate this. The RFC should commit to a parity test asserting baked global frontmatter == what the template emits at `guarded`, or parity will rot. **(should-fix)**
- **Verdict on strategy:** sufficient for emission + lint + prose; runtime-denial-untested is correctly out of scope and documented.

---

## Blocking concerns (request-changes)

1. **Config shapes / list-replace footgun** — pin every user-extensible structure (allowlist, tool→risk map) to dict shape and document list-replace semantics, or add a custom `policy` merge. The config fence never shows the allowlist/map shape. (§1)
2. **"Drop read-only wording" must be a P1 MUST, not a recommendation** — shipping the policy with "read-only" prose surviving ([agents/carter-engineer.md](agents/carter-engineer.md#L43), [agents/carter-architect.md](agents/carter-architect.md#L39)) actively worsens posture. (§2)
3. **Bash bypass missing from the enforcement model** — add bash-command gating (OpenCode `permission.bash`, Copilot `hooks`) as the vector for shell-invoked R2/R3/R5, and mark VS Code unable. (§2)
4. **Escape hatch conflates logging with authorization** — define the override per enforcement tier; the `carter-ops audit` path is the ledger, not the gate. (§4)

## Security findings (severity)

- **HIGH (honesty):** "read-only" wording is a credential guarantee the design cannot make; tool-name denial is honest defense-in-depth only once the wording is dropped. (§2)
- **MEDIUM (residual):** single full-scope token shared globally ([installer.py](carter/installer.py#L271), [mcp/copilot/github.json](mcp/copilot/github.json#L6)) — blast radius unchanged by tool-name denial; scoped-tokens deferral is defensible *with* honest labeling. (§2)
- **MEDIUM (gap):** bash/shell path reaches the same token irrespective of MCP tool-name denial; unenforceable on VS Code. (§2)

## DECIDE items (human call)

- **Q3 — token blast radius:** recommend ship guarded-by-default **with** the mandatory wording-drop; file scoped tokens as a follow-up RFC; record residual risk in policy docs. Residual = MEDIUM, acceptable for a scaffolder whose dominant threat is accidental model action.
- **Q6 — default level:** out of my lane (UX), but note: `guarded`-by-default is only honest once findings #2/#3 land — otherwise "guarded" overpromises on VS Code/Copilot.
- **Q14 — global agent policy:** baked-default vs install-time file — both feasible; baked-default is simpler but adds the parity test obligation (§6 Gap 2).
