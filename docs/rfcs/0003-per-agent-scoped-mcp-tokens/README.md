---
id: RFC-0003
status: draft                 # draft | review | accepted | rejected | withdrawn
revision: 1
created: 2026-06-12
decided: null
author: mauriciomem
adr: null
plan: null
supersedes: []
tags: [security, mcp, tokens, secrets, policy, deferred]
---

# RFC-0003: Per-agent scoped MCP tokens

**Status:** Draft
**Revision:** 1
**Author:** mauriciomem

> **Parking document — investigate later.** This is the deferred **Q3(b)** effort
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

[Pending — this RFC is parked in `draft`. Promote to `review` only when the Q3(b)
investigation is taken up. If superseded or declined, record the rationale here.]
