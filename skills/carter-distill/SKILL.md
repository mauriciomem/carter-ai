---
name: carter-distill
description: Promote quick notes from /memories/ into curated knowledge entries in ~/.copilot/knowledge/
argument-hint: "[optional: topic filter]"
---

<objective>
Review recent notes in `/memories/` and promote valuable learnings into structured, curated entries in `~/.copilot/knowledge/`.
</objective>

<workflow>

## Distill Process

1. **Read** — Scan all notes in `/memories/` (user-scope and repo-scope).

2. **Classify** — For each note, determine which knowledge topic it belongs to:
   | Topic File | Content Type |
   |-----------|-------------|
   | `decisions.md` | Architecture decisions, trade-off analyses |
   | `mistakes.md` | Mistakes made and lessons learned |
   | `patterns.md` | Recurring design patterns and proven solutions |
   | `debugging.md` | Debugging techniques and root cause analyses |
   | `infrastructure.md` | Infrastructure patterns, cloud configurations |
   | `project-history.md` | Project milestones and outcomes |

3. **Deduplicate** — Check existing entries in the target knowledge file. Skip if a substantially similar entry already exists.

4. **Format** — Structure each new entry:
   ```markdown
   ## YYYY-MM-DD | Title
   - **Context:** Where this happened (repo, file, project)
   - **[Topic-specific fields]:** ...
   - **Tags:** comma-separated keywords
   ```

5. **Append** — Add new entries to the appropriate knowledge file.

6. **Report** — Show the user what was promoted:
   - Number of notes reviewed
   - Number of entries created per topic
   - Any notes skipped (duplicates or unclear)

7. **Suggest cleanup** — Recommend which `/memories/` notes can be deleted now that they've been promoted.

</workflow>

<guidelines>
- Only run on-demand (when the user asks). Never auto-distill.
- Preserve the user's original intent — don't rephrase so aggressively that meaning is lost.
- When in doubt about classification, ask the user.
- If a note spans multiple topics, create entries in each relevant file.
</guidelines>
