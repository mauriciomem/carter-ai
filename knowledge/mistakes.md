# Mistakes & Lessons Learned

> Mistakes and corrective learnings tracked by Carter to avoid repetition.

<!-- Entries are added by the carter-distill skill. Format:
## YYYY-MM-DD | Title
- **Context:** ...
- **Mistake:** ...
- **Fix:** ...
- **Lesson:** ...
- **Tags:** ...
-->

## 2026-06-04 | Code review surfaced out-of-scope findings
- **Context:** A PR review run through `carter-code-review` cited files that were not part of the PR (untracked/ignored artifacts like `__pycache__/` and `.vscode/`), lowering the review's quality.
- **Mistake:** The skill had no scoping discipline — it encouraged ranging across the whole working tree (`grep -rn "."`) and never gated findings against the PR's changed-file set or `.gitignore`.
- **Fix:** Added a `<scope-gate>` to `carter-code-review`: determine the change set first (`git diff <base>...<head> --name-only`, or the API diff for GitHub MCP), search with `git grep` not `grep -rn`, and require every finding to be attributable to the change. Added scoping commands to `carter-pipeline`.
- **Lesson:** Scope review tooling to tracked/changed content up front. A finding must be *attributable to the PR's change* — not merely present somewhere in the tree. "Tracked" ≠ "in the PR"; and in GitHub-MCP reviews the API diff is the authoritative scope (no `git` available). Avoid absolute "untracked → drop" rules: legitimately-new local files and cross-file impacts of a change are still in scope.
- **Tags:** code-review, git, scope, false-positives, carter-code-review
