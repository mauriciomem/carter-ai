---
name: carter-reflect
description: Analyze accumulated memory and knowledge to propose improvements to Carter agent and skill files
argument-hint: "[optional: focus area or specific agent/skill]"
---

<objective>
Read accumulated memory (`~/.carter/memories/`) and curated knowledge (`~/.carter/knowledge/`) to identify recurring patterns, then propose concrete improvements to Carter's agent definitions or skill files.

**Language:** proposals and notes follow the workspace `docs_language` (`.carter/carter.yaml`; default English); edits to agent and skill files are always English.
</objective>

<workflow>

## Reflect Process

1. **Read memory** — Scan all files in `~/.carter/memories/` (user, session, and repo scopes).

2. **Read knowledge** — Scan all files in `~/.carter/knowledge/`, focusing on `mistakes.md`, `patterns.md`, and `debugging.md`.

3. **Identify patterns** — Look for:
   - Mistakes that recur across conversations (same root cause, different surface)
   - Workarounds that should be codified as guidelines
   - Missing instructions that led to agent failures
   - Skill gaps — tasks the user repeatedly corrects the agent on
   - Outdated rules that no longer apply

4. **Map to targets** — For each pattern, identify which file should change:
   | Pattern Type | Target File |
   |-------------|-------------|
   | Agent behavior issue | `agents/carter-*.md` |
   | Missing domain knowledge | `skills/carter-*/SKILL.md` |
   | Global rule gap | `instructions/copilot-instructions.md` |
   | OpenCode-specific gap | OpenCode `AGENTS.md` |

5. **Propose changes** — For each improvement, show:
   - **Source evidence**: Which memory/knowledge entries revealed the pattern
   - **Target file**: The agent or skill file to modify
   - **Proposed edit**: The specific text to add, change, or remove
   - **Rationale**: Why this change prevents future issues

6. **Apply with approval** — Present all proposals to the user. Apply only the changes the user approves.

7. **Record** — After applying changes, record the improvement in `~/.carter/knowledge/decisions.md` as an architecture decision.

</workflow>

<guidelines>
- Only run on-demand. Never auto-reflect.
- Be conservative — propose changes only when the evidence is clear and repeated. A single mistake is not a pattern.
- Do not change agent routing or skill ownership. Only change guidelines, rules, and domain knowledge.
- Cite specific memory/knowledge entries as evidence. Do not propose changes based on hunches.
- Prefer adding guidelines over removing them. If a rule seems outdated, flag it for the user rather than deleting.
- Keep proposals minimal — one change per pattern. Do not bundle unrelated changes.
</guidelines>
