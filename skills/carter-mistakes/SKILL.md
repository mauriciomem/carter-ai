---
name: carter-mistakes
description: Record mistakes and lessons learned to Carter's memory system
argument-hint: "[mistake or lesson to record]"
---

<objective>
Capture mistakes, failures, and lessons learned into Carter's memory system for future reference. The goal is to prevent repetition by building a searchable knowledge base of what went wrong and why.

**Language:** write memory entries in the workspace `docs_language` (`.carter/carter.yaml`); if it is absent, English unless the user chose another language.
</objective>

<workflow>

## Recording Process

1. **Identify the mistake** — What went wrong? Be specific about the failure.

2. **Capture context** — Where did this happen?
   - Repository/project
   - File/component
   - What was being attempted

3. **Root cause** — Why did it happen? Go beyond surface-level symptoms.

4. **Fix** — What was done to resolve it?

5. **Lesson** — What should be done differently next time? This is the most important part.

6. **Write to memory** — Store as a structured note in two locations:

   **Primary (visible)** — Write to `~/.carter/memories/user/` (or `~/.carter/memories/repo/<repo-name>/` if the mistake is project-specific):
   ```markdown
   ## Mistake: [Title]
   - **Date:** YYYY-MM-DD
   - **Context:** [repo/project, what was being done]
   - **What went wrong:** [specific failure]
   - **Root cause:** [why it happened]
   - **Fix:** [what resolved it]
   - **Lesson:** [what to do differently]
   - **Tags:** [keywords for searchability]
   ```

   **Secondary (platform)** — Also write the same note to `/memories/` using the platform memory tool (for auto-loading in VS Code). On surfaces where the platform memory tool is unavailable, skip this step.

7. **Suggest distill** — If there are several accumulated notes, suggest running `carter-distill` to promote them to the curated knowledge base.

</workflow>

<guidelines>
- No blame — focus on the systemic cause, not who did it.
- Be specific — "Terraform apply failed" is not useful. "Terraform apply failed because the S3 bucket policy referenced a deleted IAM role" is.
- Check for existing entries — before recording, check `~/.copilot/knowledge/mistakes.md` and `~/.carter/memories/` for duplicates.
- Tags matter — they enable future searchability. Include technology, error type, and domain.
</guidelines>
