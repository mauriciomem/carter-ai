---
step: 4
status: done
depends_on: [1]
files_modified: [carter/config.py, carter/scaffold.py, templates/base_agent.md.j2, agents/carter-maestro.md, agents/carter-architect.md, agents/carter-engineer.md, agents/carter-devops.md, agents/carter-pm.md, agents/carter-learner.md, agents/carter-narrator.md, tests/test_scaffold.py, tests/test_parity.py]
---

## Step 4 — Per-target frontmatter emission (P2)

Emit the per-agent allowlist + gates into **agent frontmatter**, per target, using
the most authoritative native primitive (ADR-0005 D2/D3). Per-agent MCP scope goes
in **agent frontmatter** — `configure_mcp_servers` stays global-only.

### Tasks
- OpenCode: emit `permission` (allow|ask|deny, incl. bash command globs) — **not**
  the deprecated `tools` boolean.
- VS Code / Copilot: emit the enforced `tools:` allowlist + per-agent MCP scope
  (`tools: [server/*]` / `mcp-servers`); emit `hooks` deny/ask where available.
- Drive emission from the step-1 model (`min(level gate, per-agent allowlist)`).
- Emit `loose` + `guarded` only — **`strict` is held by the P2→P3 gate** (lands in
  step 9).

### Done when (TDD red → green)
- Per-target tests assert each agent's emitted frontmatter matches its declared
  allowlist + the active level's gates (devops gets R2/R3/R5; narrator R0/R1/R6).
- A test asserts `configure_mcp_servers` is unchanged (per-agent scope lives in
  frontmatter, not the global wiring).
- Ties back to must_have: "each agent emits a per-agent tool allowlist + per-target
  gates in agent frontmatter …".
