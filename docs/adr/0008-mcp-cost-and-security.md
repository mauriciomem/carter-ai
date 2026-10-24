---
id: ADR-0008
status: accepted
created: 2026-06-15
decided: 2026-06-15
supersedes: []
superseded_by: null
rfc: RFC-0004
tags: [mcp, cost, tokens, security, github, installer]
---

# ADR-0008: MCP tool-surface — opt-in install + official read-only GitHub server

**Status:** Accepted
**Date:** 2026-06-15
**Deciders:** mauriciomem (author), carter-architect + carter-engineer (RFC-0004 reviews, approve)

## Context

Carter is a **scaffolder, not a runtime** — it emits agent/skill/MCP config and exits
([ADR-0005](0005-risk-based-strictness-policy.md); `carter/resources.py`). It can shape
only the **static payload** it writes, never live in-conversation context.

Verified facts driving this decision (full evidence in
RFC-0004 (record removed 2026-10) + its `verification.md`):

- **Both harnesses are token-metered (since 1-Jun-2026).** Copilot bills **GitHub AI
  Credits** = model × (input+output+cached) tokens, 1 credit = $0.01; OpenCode BYO-key
  is per-token. Token volume = money on both ([RFC-0004 §P3]).
- **MCP tool schemas are the largest Carter-controlled per-request surface** — bigger
  than all of Carter's prose (~1.6–2.5k tok, already lean). Carter ships **three** MCP
  servers (github/terraform/atlassian) wired **globally** to every workspace
  (`configure_mcp_servers`, `carter/installer.py` ~L786), and ships the **archived**
  `@modelcontextprotocol/server-github`.
- **Measured (RFC-0004 §V3):** archived GitHub server = **3,963 tok** (leanest *useful*
  config, ~152 tok/tool). The official `github/github-mcp-server` is **~4× more
  verbose/tool**: scoped+read-only = 13,977; surgical `--tools` read-only = **6,650
  (+68%)**. The premise *"swap to the official server to shrink tokens"* is **false** —
  the official server **costs** tokens. Its value is **maintenance** (the reference
  server is archived) + a real **`--read-only`** switch the archived server lacks.

## Decision

A single coherent change to Carter's MCP tool surface, three interdependent
sub-decisions:

- **D1 — MCP server opt-in (the token win).** `carter install` ships only the MCP
  servers a workspace selects; an unused server (e.g. terraform/atlassian in a
  GitHub-only workspace) is not wired and adds **zero** tool-schema tokens. The
  hardcoded `["github","terraform","atlassian"]` triple is lifted to one constant
  consumed by both install and uninstall.
- **D2 — Official read-only GitHub server (the security buy).** Replace the archived
  server with the official `github/github-mcp-server` run via **Docker**
  (`ghcr.io/github/github-mcp-server`, **pinned by digest**), in **read-only** mode with
  a **surgical `--tools`** allowlist (single server — "A′"). **Security is preferred
  over token cost on this credential path** (explicit user decision): the **+68%** token
  cost is accepted for a maintained server + removal of the MCP write-tool surface.
  GitHub **writes go via the shell/`gh` path**, governed by
  RFC-0002 (record removed 2026-10) — not via MCP.
- **D3 — Round-trip guardrails (the low-effort cost half).** Reinforce spec/TDD-first as
  the default posture to cut **retry loops**, and add usage-doc guidance (`@`-mention
  specialists directly; batch file reads) to cut **redundant** hops. The Maestro
  delegation-economy rule is **deferred**.

**Transport:** Docker (proven on-host, RFC-0004 §V4); remote-HTTP documented as the
no-Docker fallback.

## Options Considered

### Option 1: Keep the archived server + global wiring (status quo)
- **Pros:** token floor (3,963 tok); zero effort.
- **Cons:** ships an **archived/unmaintained** server (no security fixes); **no
  read-only** switch (all 26 tools incl. writes exposed); pushes unused servers' schemas
  to every workspace.

### Option 2: Swap to the official server "to shrink tokens" (RFC-0004 r2 premise)
- **Pros:** would be a clean cost+security win — if the premise held.
- **Cons:** **falsified** by measurement — the official server costs **+68% to +570%**
  tokens. Rejected as a *cost* rationale.

### Option 3 (CHOSEN): Opt-in install (D1) + official read-only Docker GitHub server (D2) + guardrails (D3), single-server "A′"
- **Pros:** captures the real token win where it exists (D1); maintained + locked-down
  GitHub access (D2); honest cost accounting; simplest installer change.
- **Cons:** +68% tokens on the GitHub server; new Docker prereq.

### Option 4: Option 3 but with "B" (separate `github-ro` + `github-rw` instances)
- **Pros:** native MCP write path for devops/narrator.
- **Cons:** two server defs + per-agent frontmatter wiring complexity for a benefit no
  workflow needs (shell/`gh` already writes under RFC-0002). Rejected.

## Rationale

- **Separate cost from security, honestly.** D1 is the cost lever; D2 is bought for
  security and is *not* sold as savings. This prevents a future session "optimizing" by
  swapping servers expecting a token cut.
- **Security > token cost on the GitHub credential path** (user decision): an
  unmaintained server mediating repository access is a standing risk; `--read-only`
  removes the accidental-write vector at the model surface.
- **A′ over B:** the shell/`gh` write path already exists under RFC-0002; native MCP
  writes add complexity no workflow requires (RFC-0004 OQ4).
- **Docker over remote-HTTP:** proven on-host (V4), self-contained, deterministic,
  offline-capable; remote-HTTP is the documented fallback.
- **Levers 7–8 declined:** Carter's prose is already lean; trimming risks the
  *"minimal ≠ short"* accuracy loss for tokens dwarfed by the MCP surface.

## Consequences

### Positive
- Workspaces stop paying tool-schema tokens for servers they don't use (D1).
- GitHub MCP access is **maintained** and **read-only** — write-tool surface removed (D2).
- Honest cost accounting recorded; the "swap saves tokens" mistake is documented as false.
- Fewer retry/redundant round trips from the guardrails (D3, directional).

### Negative
- The GitHub server costs **+~2,700 tok/request (+68%)** vs the archived one.
- **New Docker prereq** for the official server (remote-HTTP fallback documented).
- Installer + uninstall + MCP-wiring tests must change.

### Risks
- **Docker not installed** → GitHub server fails. *Mitigation:* remote-HTTP fallback +
  explicit prereq docs.
- **`:latest` drift** → non-reproducible installs. *Mitigation:* pin the image **digest**.
- **"read-only" misread as "cannot write at all."** *Mitigation:* explicit
  MCP-surface-only doc clause (writes via shell under RFC-0002).

## References

- RFC-0004 (record removed 2026-10) + its
  verification.md (record removed 2026-10) (V3 token
  measurements; V4 transport).
- RFC-0002 (record removed 2026-10) (bash-path governance);
  RFC-0003 (record removed 2026-10) (scoped tokens — separate
  concern, not addressed here).
- [ADR-0005](0005-risk-based-strictness-policy.md) (scaffolder posture; global MCP wiring).
- GitHub — `github/github-mcp-server` (`--tools`, `--read-only`, toolsets):
  <https://github.com/github/github-mcp-server>
- GitHub Docs — Usage-based billing (AI Credits, token-metered):
  <https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals>
- Executed by plan `003-mcp-cost-and-security` (`.carter/state/plans/`).
