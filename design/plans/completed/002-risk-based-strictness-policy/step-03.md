---
step: 3
status: done
depends_on: [1]
files_modified: [docs/reference/frontmatter.md]
---

## Step 3 — Frontmatter schema docs (policy + per-agent + global-policy)

Document the new config + frontmatter surface in the **canonical** schema home
(`docs/reference/frontmatter.md` — "on any discrepancy this wins"). Docs only, no
behavior change.

### Tasks
- Add the `carter.yaml` **`policy` block** schema (level / unknown_tool /
  overrides / audit_overrides) with the dict-shaped tool→risk map + allowlist.
- Add the **per-agent** frontmatter schema Carter emits (allowlist + gates +
  per-agent MCP scope) per target — OpenCode `permission`, VS Code/Copilot
  `tools:` + `mcp-servers`.
- Add the **global-policy** baked-defaults note for global agents (no `carter.yaml`
  in scope; Q14 / D6 — hand-edited statics kept honest by `test_parity`).

### Done when
- `frontmatter.md` carries all three schemas; field names match the step-1 model
  **exactly** (no schema↔code drift).
- Ties back to must_have artifact: "docs/reference/frontmatter.md updated with the
  `policy` block + per-agent + global-policy frontmatter schema".
