# Design records — plan archive

> **ADRs and RFCs moved back to [`docs/adr/`](../docs/adr/) and
> [`docs/rfcs/`](../docs/rfcs/)** to restore dogfooding of the shipped storage
> conventions ([ADR-0007](../docs/adr/0007-rehome-records-dogfood.md), partially
> superseding [ADR-0006](../docs/adr/0006-repo-records-relocation.md)).

This folder now holds only the **tracked archive of completed execution plans** —
the public record of how the early decisions were implemented:

| Plan | Implemented |
|------|-------------|
| [`plans/completed/001-adr-0003-validator-hardening`](plans/completed/001-adr-0003-validator-hardening/) | ADR-0003 validator hardening |
| [`plans/completed/002-risk-based-strictness-policy`](plans/completed/002-risk-based-strictness-policy/) | RFC-0002 / ADR-0005 strictness policy |

**New** plans are *not* tracked here. carter-ai now keeps a private, git-ignored
`.carter/` plan workspace (versioned in its own nested `.carter/.git`), matching
the `carter-plan` skill's `.carter/state/plans/` convention (ADR-0007 §D2).
