# Design records

This folder holds **carter-ai's own project records** — the decisions, proposals,
and execution plans behind building Carter itself. It is distinct from
[`docs/`](../docs/), which holds permanent *product* documentation (how to use
Carter). The split is recorded in [ADR-0006](adr/0006-repo-records-relocation.md).

| Folder | Contents |
|--------|----------|
| [`adr/`](adr/) | Architecture Decision Records — the durable decisions (Nygard format) |
| [`rfcs/`](rfcs/) | Requests for Comments — design proposals + their reviews ([index](rfcs/README.md)) |
| [`plans/`](plans/) | Execution plans that implemented accepted RFCs/ADRs (completed) |

> **Note on the shipped tool.** The `carter-adr` / `carter-rfc` / `carter-plan`
> skills scaffold these artifacts into `docs/adr/`, `docs/rfcs/`, and
> `.carter/state/plans/` in *end-user* workspaces. That product convention is
> unchanged — `design/` is where the **carter-ai repository** keeps its own records
> (ADR-0006 D4).
