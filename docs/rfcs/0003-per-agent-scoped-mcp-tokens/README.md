---
id: RFC-0003
status: withdrawn             # draft | review | accepted | rejected | withdrawn
revision: 1
created: 2026-06-12
decided: 2026-06-28
author: mauriciomem
adr: null
plan: null
supersedes: []
tags: [security, mcp, tokens, secrets, policy]
---

# RFC-0003: Per-agent scoped MCP tokens

**Status:** Withdrawn (2026-06-28)
**Revision:** 1
**Author:** mauriciomem

> **⚠️ WITHDRAWN 2026-06-28 — do not treat the body below as current.** The
> Problem table and dependency chain are anchored to a pre-refresh codebase and to
> [RFC-0002](../0002-risk-based-strictness-policy/), which has since been
> **superseded in full** by [RFC-0005](../0005-native-subagent-orchestration/) /
> [ADR-0010](../../adr/0010-agent-platform-refresh.md). The headline benefit (an
> honest "read-only" guarantee) is absorbed by
> [ADR-0008](../../adr/0008-mcp-cost-and-security.md) D2's `--read-only` GitHub
> server. See **§ Decision** at the bottom for the full rationale and re-open
> criterion. Retained (not deleted) per the supersede-don't-edit rule (ADR-0004 §D4).

> **[Historical] Parking document — investigate later.** This is the deferred **Q3(b)** effort
> split out of [RFC-0002](../0002-risk-based-strictness-policy/) (Risk-Based
> Strictness Policy). RFC-0002 chose **Q3(a)**: ship `guarded` and *drop the
> "read-only" wording* where it can't be enforced, accepting the residual
> token blast radius (rated MEDIUM) rather than investing in scoped tokens now.
> This RFC captures the **Q3(b)** alternative — genuinely reducing the blast
> radius via per-agent scoped credentials — so it is not lost. It is **not ready
> for review**; it is a problem statement plus the questions to answer when picked up.

## Summary

Today every Carter MCP server receives **one full-scope token per service**, shared
across all agents. A "read-only" agent still holds a write-capable credential; the
only thing standing between it and a write is tool-name denial (where the target
supports it) and prose. This RFC explores **per-agent scoped tokens** so that the
*credential itself* — not just the emitted tool allowlist — enforces least privilege.

## Problem

Verified current state (grounding for the fresh session that picks this up):

| Claim | Reality | Evidence |
|---|---|---|
| MCP tokens are least-privilege | One full-scope token per service, shared globally | `REQUIRED_ENV_VARS` = `GITHUB_TOKEN` / `TF_TOKEN` / `ATLASSIAN_*` (`carter/installer.py:271`) |
| Token is injected per agent | Injected per **server**, identical for every agent | `mcp/copilot/github.json` / `mcp/opencode/github.json` wire `GITHUB_TOKEN: ${GITHUB_TOKEN}` |
| "read-only" access is a credential guarantee | It is a *tool-name* guarantee at best; the token can still write | RFC-0002 Q3 (accepted residual risk) |

RFC-0002's tool-name denial reduces *which calls a compliant agent will make*. It
does **not** reduce *what the credential can do* if a call escapes the allowlist
(bash path, a non-denied tool, a future MCP method). The blast radius is the token.

## Proposal (to be developed)

Sketch only — the real proposal is the work of this RFC when it leaves draft:

- A per-agent (or per-risk-tier) credential model: e.g. a read-scoped GitHub token
  for `R0`-only agents, a write-capable token reachable only by `devops`/`narrator`.
- A way to provision/inject distinct credentials per agent without leaking the
  high-scope token into low-scope agent environments.
- Reconciliation with RFC-0002's policy model: scoped tokens would let the policy
  *honestly* claim "read-only" again, upgrading several `ask`/prose gates to real
  credential-level denial.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **Per-agent scoped tokens (this RFC)** | Real least-privilege; restores honest "read-only"; defense-in-depth under the allowlist | Provisioning/rotation complexity; per-provider scope models differ (GitHub fine-grained PAT vs TF team token vs Atlassian); UX of managing N tokens |
| **Tool-name denial only (RFC-0002 Q3(a), shipped)** | Zero new credential management; works today | Blast radius unchanged; "read-only" stays a soft guarantee |
| **Single token, prose only (status quo before RFC-0002)** | Simplest | The exact problem — unenforceable |

## Trade-offs / Impact

- Touches the installer token wiring (`carter/installer.py`), the per-target MCP
  configs (`mcp/**`), and the policy/emission model from RFC-0002.
- Per-provider scoping is **not uniform** — GitHub fine-grained PATs, Terraform
  team/org tokens, and Atlassian scoped tokens each have different capability models;
  the design must survive the lowest common denominator.
- Likely depends on RFC-0002 landing first (the policy model defines *which* agent
  needs *which* scope).

## Open questions

- **OQ1 — Granularity.** Per-agent, or per-risk-tier (read vs write), or per-category?
- **OQ2 — Provisioning.** Who mints the scoped tokens — the user (documented manual
  setup) or an automated flow? How are they injected without cross-agent leakage?
- **OQ3 — Provider parity.** What is the least-common-denominator scope model across
  GitHub / Terraform / Atlassian, and where does it degrade to "best effort"?
- **OQ4 — Rotation & expiry.** How are scoped tokens rotated; what happens on expiry
  mid-session?
- **OQ5 — Dependency on RFC-0002.** Must RFC-0002 be accepted/implemented first, or
  can this proceed in parallel?

## Decision

**Withdrawn 2026-06-28** (author: mauriciomem). The Q3(b) investigation is dropped,
not parked — the model it was written against moved out from under it. Three reasons:

1. **Its stated dependency is dead.** RFC-0003 sequenced itself behind RFC-0002
   ("depends on RFC-0002 landing first"; OQ5). [RFC-0002 is superseded in full by
   RFC-0005 / ADR-0010](../../adr/0010-agent-platform-refresh.md). The taxonomy it
   assumed (a "read-only tier", R0/R4/R6) was collapsed to four categories with
   secret-access folded into `remote-write` (`carter/config.py` `RISK_TAXONOMY`).

2. **The shipped enforcement model is stronger than the body claims.** The Problem
   table asserts "the only thing standing between a read-only agent and a write is
   tool-name denial and prose." Against the current (ADR-0010) model that is false:
   per-agent MCP **tool scoping** ships in agent frontmatter (`AGENT_MCP_SCOPE` →
   `tools:`; a read agent cannot call a write tool), the per-agent **allowlist is
   category-level deny-by-default** (`AGENT_ALLOWLIST`; devops is the sole holder of
   `remote-write`/`dangerous`), and the OpenCode **bash path is glob-denied per
   category** (`_opencode_bash`) — closing the exact "bash-path escape" this RFC names.

3. **Its headline benefit is already decided elsewhere.** "Genuinely reducing the
   blast radius … so the policy can honestly claim read-only again" is delivered by
   [ADR-0008](../../adr/0008-mcp-cost-and-security.md) D2's official `--read-only`
   GitHub server (pending execution in plan `003-mcp-cost-and-security`), which
   removes the MCP write surface without minting, injecting, or rotating per-agent
   tokens — avoiding this RFC's OQ2–OQ4 entirely. The only residual unique to scoped
   tokens — abuse of the raw `GITHUB_TOKEN` env var *past* the read-only MCP surface
   and the bash governance — was unquantified here and was already accepted as
   **MEDIUM** when RFC-0002 chose Q3(a).

**Re-open criterion (narrow).** If a *measured* incident or threat model shows the
raw service token being abused **past** the read-only MCP surface (ADR-0008) and the
bash/`gh` governance (ADR-0010), file a **fresh** RFC scoped against the then-current
model — do not revive this text; its premises are anchored to the pre-refresh
codebase and a superseded RFC.
