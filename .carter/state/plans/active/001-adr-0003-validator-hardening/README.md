---
id: 001-adr-0003-validator-hardening
status: proposed
created: 2026-06-09
updated: 2026-06-09
adr: ADR-0003
push_policy: manual
tags: [validator, plans, recovery, hardening]
repos: [carter-ai]
must_haves:
  truths:
    - "carter check flags a checkpoint whose active_plan points at a non-existent plan"
    - "carter check flags a status/folder mismatch (completed-status plan in active/, or active-status in completed/)"
    - "an unrecognized must_haves sub-key is reported, not silently counted as zero"
    - "a step-NN.md with a non-integer step, or a step that disagrees with its filename, is rejected"
    - "a plan listing more than 3 steps in prose (no table) is still flagged as needing step files"
    - "commit_state surfaces a failed git add instead of reporting 'nothing to save'"
  artifacts:
    - "red-then-green tests covering every new validation branch"
  key_links:
    - "docs/adr/0003-knowledge-adr-rfc-plan-storage.md"
---

# Plan: ADR-0003 validator hardening & recovery integrity

## Objective
Capture the post-implementation review findings (Yui, 2026-06-09) for the
ADR-0003 plan/checkpoint system. These are sharp edges on a correct shape — no
redesign, no scope change. Each step is an independently shippable, TDD-first
pass. Tracked now; implemented later.

> Source: review of the merged ADR-0003 stack (commits `b78a385..0a078ac`). The
> first quality-gate audit cleared critical/high; these are the lenient-validation
> and recovery-integrity gaps a second read surfaced.

## Milestones
| # | Milestone | Deliverables |
|---|-----------|--------------|
| M1 | Recovery integrity | checkpoint↔plan + folder↔status cross-checks |
| M2 | Validator strict mode | reject malformed must_haves / dates / steps / prose-steps |
| M3 | Correctness nits | commit_state git-add, docstring, id collision |
| M4 | Honesty + coverage | opt-in-validation note + end-to-end recovery test |

## Steps
| # | Step | Status | File |
|---|------|--------|------|
| 1 | Recovery integrity (Tier 1: #1 #2) | pending | step-01.md |
| 2 | Validator strict mode (Tier 2: #3 #4 #5 #6) | pending | step-02.md |
| 3 | Correctness nits (Tier 3: #7 #8 #9) | pending | step-03.md |
| 4 | Honesty note + test gaps (A B) | pending | step-04.md |

## Risks
- #1/#2 need the validators to see plans-root context they currently lack — a
  small signature change to `validate_checkpoint`/`validate_plan_dir`, not a redesign.
- Strict-mode changes (#3–#6) may flag pre-existing real plans; introduce as hard
  errors only after confirming no in-repo plan trips them.

## Notes
This plan is itself a dogfood of the structure it audits: it lives at
`.carter/state/plans/active/001-adr-0003-validator-hardening/`, carries the D6
frontmatter, tiers into step files (>3 steps), and passes `validate_plan_dir`.
