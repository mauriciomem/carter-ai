# Patterns

> Recurring design patterns and proven solutions tracked by Carter.

<!-- Entries are added by the carter-distill skill. Format:
## YYYY-MM-DD | Title
- **Context:** ...
- **Pattern:** ...
- **When to use:** ...
- **Example:** ...
- **Tags:** ...
-->

## 2026-06-05 | Review registers and intent labels for review output
- **Context:** PR review and code-review output felt robotic — one rigid severity table for every change, no detail levels, bare assertions without rationale, and mechanical "always praise" filler.
- **Pattern:** Three review registers — **Quick** (prose, top 1–3 labeled findings, no table), **Standard** (default; short summary + labeled bullets with one-line *why*), **Deep** (full severity table). Findings use Conventional-Comments intent labels (`issue/suggestion/nitpick/question/praise/note`) with `(blocking|non-blocking)`; severities (Critical/Major/Minor/Nit) are kept only in the Deep table and mapped to labels. Voice rules: comment on the code not the author, explain *why*, praise only when genuine.
- **When to use:** Any code or design review, and any review body posted to a PR via `ops:` `gh-pr`/`gh-pr-comment` (default Standard).
- **Example:** `issue (blocking): unparameterized SQL — f-string lets `id` inject arbitrary SQL; use a parameterized query.`
- **Tags:** code-review, pr, tone, conventional-comments, carter-code-review

