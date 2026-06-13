---
step: 2
status: done
depends_on: []
files_modified: [agents/carter-architect.md, agents/carter-engineer.md, agents/carter-learner.md, agents/carter-pm.md, tests/test_parity.py]
---

## Step 2 — Drop the false "read-only" prose (P1 MUST)

The shared full-scope MCP token (`installer.py:271`) makes "read-only" a false
guarantee (ADR-0005 D5). Remove the wording at **all four** static agents **and**
their templates. This is **body prose**, so `test_parity` (frontmatter-only) will
not catch a relapse — add an explicit guard (carried N3).

### Tasks
- Remove/rewrite the "read-only access" wording at: `agents/carter-architect.md:39`,
  `agents/carter-engineer.md:43`, `agents/carter-learner.md:40`,
  `agents/carter-pm.md:42`.
- Mirror the edit in each corresponding `templates/agents/*.j2` so `carter update`
  re-emits the honest text (statics are raw-copied at `installer.py:498`).

### Done when (TDD red → green)
- A test greps the four statics **and** their templates and asserts the
  "read-only" claim is gone (red before the edit, green after) — closes the
  frontmatter-parity gap (carried N3).
- Ties back to must_have: "the false 'read-only' wording is removed from all four
  static agents … AND their .j2 templates".
- Test suite green.

### Outcome
The `.j2` templates carry **no `<mcp>`/Tool Access block** (different design per
ADR-0002), so the false wording lived **only** in the four static `agents/*.md`;
no template edit was needed. The guard test asserts both sources stay clean, so a
future template relapse is still caught.
