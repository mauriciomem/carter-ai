---
id: 002-risk-based-strictness-policy
status: active
created: 2026-06-13
updated: 2026-06-13
adr: ADR-0005
rfc: RFC-0002
push_policy: manual
tags: [strictness, enforcement, security, policy, mcp]
repos: [carter-ai]
must_haves:
  truths:
    - "carter.yaml accepts a `policy` block (level/unknown_tool/overrides/audit_overrides) deep-merged with DICT-shaped defaults (lists would be replaced, not merged); an omitted block defaults to `loose` for existing config and `guarded` for new installs"
    - "the false 'read-only' wording is removed from all four static agents (carter-architect.md:39, carter-engineer.md:43, carter-learner.md:40, carter-pm.md:42) AND their .j2 templates"
    - "each agent emits a per-agent tool allowlist + per-target gates in agent frontmatter — OpenCode `permission`, VS Code/Copilot enforced `tools:` + per-agent MCP scope (not the global configure_mcp_servers)"
    - "`carter check` lints emitted frontmatter against the declared allowlist + the active level's gate map, detects carter.yaml-vs-installed drift, and requires a HARD ACK (with a non-interactive `--accept-degraded` flag) when the target cannot natively enforce the declared strict level"
    - "`guarded` and `strict` force a redaction pass regardless of `redaction.enabled`; `carter check` WARNs on the strict|guarded + `redaction.enabled: false` contradiction"
    - "`strict` enforcement ships only after P3 lint + escape-hatch + tests land (the P2->P3 gate)"
  artifacts:
    - "red-then-green tests for: policy config merge (dict-shaped), per-target frontmatter emission, and the carter check policy lint"
    - "docs/reference/frontmatter.md updated with the `policy` block + per-agent + global-policy frontmatter schema"
  key_links:
    - "docs/adr/0005-risk-based-strictness-policy.md"
    - "docs/rfcs/0002-risk-based-strictness-policy/README.md"
---

# Plan: Risk-Based Strictness Policy (RFC-0002 / ADR-0005)

## Objective
Implement the risk-based strictness policy from ADR-0005: a `policy` block, a
fixed risk taxonomy (R0–R6) with per-agent allowlists, and target-aware native
emission plus a `carter check` lint — shipped in three phases (P1 model, P2
emission, P3 lint+escape-hatch+tests) with a **P2→P3 gate** that holds `strict`
enforcement until P3 is green. Every step is TDD-first (red → green → refactor).

## Milestones
| # | Milestone | Deliverables |
|---|-----------|--------------|
| M1 | P1 — model + docs (no behavior change) | `policy` block + R0–R6 taxonomy + tool→risk map (dict-shaped); drop "read-only" prose; frontmatter schema |
| M2 | P2 — emission | per-agent allowlist + gates in agent frontmatter; policy-driven maestro table; migration message; D5 dedup |
| M3 | P3 — lint + escape hatch + tests (GATE) | `carter check` policy lint + hard ack + WARN; override ledger; emission/lint tests; P2→P3 gate |

## Steps
| # | Step | Status | File |
|---|------|--------|------|
| 1 | P1 policy model — config block + R0–R6 taxonomy + tool→risk map (dict-shaped) | done | step-01.md |
| 2 | P1 drop the false "read-only" prose (4 statics + templates) | done | step-02.md |
| 3 | P1 frontmatter schema docs (policy + per-agent + global-policy) | done | step-03.md |
| 4 | P2 per-target frontmatter emission (permission / tools: / MCP scope) | done | step-04.md |
| 5 | P2 policy-driven maestro table + migration message + R6 handoff | pending | step-05.md |
| 6 | P2 fold D5 — de-dup hardcoded server triple (installer.py:786, :948) | done | step-06.md |
| 7 | P3 `carter check` policy lint + hard ack + redaction WARN (folds N2) | pending | step-07.md |
| 8 | P3 single-action override ledger (`carter ops`, override ≠ authz) | pending | step-08.md |
| 9 | P3 emission/lint tests + P2→P3 gate (folds N3, optional G1) | pending | step-09.md |

## P2→P3 gate
`strict` enforcement (R3/R5 `deny`, the strict gate map) **ships only after** the
P3 lint (step 7), escape hatch (step 8), and emission/lint tests (step 9) are
green. Encoded as `step-09` `depends_on: [4, 7, 8]` — strict cannot be marked done
before its lint + escape-hatch + tests land. P2 emission (step 4) ships `loose` +
`guarded` only.

## Risks
- The `policy` block is additive, but `_deep_merge` replaces lists wholesale — the
  tool→risk map and allowlist MUST be dict-shaped or a user override wipes them.
- Per-target inequality (VS Code weakest) means `strict` degrades on some targets;
  the hard ack (step 7) must surface this, never hide it.
- The "read-only" drop is body prose → `test_parity` won't catch it; step 2 edits
  both statics and templates and adds an explicit guard (carried N3).

## Notes
Dogfoods the structure it implements: lives at
`.carter/state/plans/active/002-risk-based-strictness-policy/`, carries the D6
frontmatter, tiers into step files (>3 steps), and passes `validate_plan_dir`.
Repo test cmd: `python -m pytest tests/ evals/test_skills.py evals/test_routing.py
-q -p no:cacheprovider` (exclude `evals/test_live.py` — it hangs).
