# Decisions

> Architecture Decision Records and trade-off analyses tracked by Carter.

<!-- Entries are added by the carter-distill skill. Format:
## YYYY-MM-DD | Title
- **Context:** ...
- **Decision:** ...
- **Rationale:** ...
- **Alternatives considered:** ...
- **Tags:** ...
-->

## 2026-06-06 | Narrator first-class + docs/story skill suite (ADR-0001)
- **Context:** The narrator was the only agent without a static source (template-only), so `carter install` shipped 6 agents and never the narrator. Narrative voice was fragmented with no developer-docs or public-storytelling skill.
- **Decision:** (D1) Add `agents/carter-narrator.md` so the narrator is always installed (6→7 agents, redaction ON/7 categories baked in). (D2) New `carter-docs` skill (Diátaxis + Keep a Changelog/Conventional Commits + git-aware doc-audit). (D3) New `carter-story` skill (public-facing narrative). (D4) Terse ticket/PR/issue responses are a **Brief register**, not a skill. Skills 20→22.
- **Rationale:** Completes the dual-source agent pattern; puts style in globally-installed skills while redaction stays at the narrator agent gate; reuses the register + Scope Gate patterns; delegation (carter-adr, carter-diagram, pptx/docx) prevents drift.
- **Alternatives considered:** Keep narrator scaffold-only (rejected: orphan/inconsistent); render template at install time (rejected: Jinja in installer = over-engineering); one-skill-per-surface (rejected: overlap); mega narrate skill (rejected: kitchen sink); split into 3–4 ADRs (rejected: would duplicate/orphan the anti-drift table).
- **Tags:** architecture, agents, skills, narrator, documentation, adr-0001
