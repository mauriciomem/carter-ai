---
name: carter-code-review
description: Review code for quality, design patterns, security, and testability
argument-hint: "[file, PR, or code to review]"
---

<objective>
Perform a structured code review focusing on quality, maintainability, security, and testability. Produce actionable feedback categorized by severity.

**Language:** review comments posted to a PR or repository are in English; summaries to the user follow the conversation language.
</objective>

<scope-gate>

## Scope Gate (establish BEFORE reviewing)

A review can only comment on what the change actually touches. Establish the
scope first, then keep every finding attributable to it.

### 1. Determine the change set

The diff defines the scope. Locally, use `git diff <base>...<head> --name-only` (plus `git status --short` for uncommitted work). With GitHub MCP and no clone, the API diff *is* the scope — never infer paths outside the returned changed-file set.

### 2. Scope the search

- Use `git grep -n "pattern"` (searches tracked files only) — never `grep -rn "pattern" .`, which walks `.venv/`, `node_modules/`, `__pycache__/`, `.vscode/`, and build output.
- For PR-only impact, prefer searching within the changed-file set rather than all tracked files.

### 3. Gate every finding

- A finding must be **attributable to the change** — either located in a changed file/line, or it must name the specific change that breaks an otherwise-untouched file (e.g. "this PR renames `foo()` but its caller here still uses the old signature").
- Filter ignored/untracked artifacts as a **class**: once you dismiss one (e.g. `__pycache__/`), apply the same rule to every hit in the pass (`.vscode/`, `dist/`, etc.). Use `git check-ignore <path>` to settle borderline cases.
- A finding that is neither in the change nor attributable to it is **out of scope** — drop it.

</scope-gate>

<review-register>

## Review Register (choose the level of detail)

Match the format to the size of the change and what was asked. Default to
**Standard**. Honor explicit cues like "quick review" or "deep review."

| Register | Use when | Shape |
|----------|----------|-------|
| **Quick** | Small/single-file diffs, or "quick look" | Conversational prose. Top 1–3 findings as labeled lines, blocking first. No table. |
| **Standard** (default) | Most PRs | 2–3 sentence plain summary, then findings as labeled bullets (one line of *why* each). Praise only if genuine. |
| **Deep** | Large or architectural PRs, or "deep review" | The full severity-table report (see Output Format). |

### Finding labels (Quick & Standard)

Use intent labels so the author can triage by what you're actually asking for:

`label (blocking|non-blocking): subject` — then an optional one-line *why*.

- `issue` — a real problem (bug, security, broken behavior)
- `suggestion` — a concrete improvement
- `nitpick` — trivial/preference, always non-blocking
- `question` — you're unsure; asking for clarification
- `praise` — genuine; never fabricated
- `note` — FYI, non-blocking

### Mapping to severities (Deep table)

The Deep register keeps the severity vocabulary; the labels map cleanly:

| Severity (Deep) | Label (Quick/Standard) |
|-----------------|------------------------|
| Critical / Major | `issue (blocking)` |
| Minor | `suggestion (non-blocking)` |
| Nit | `nitpick (non-blocking)` |

</review-register>

<voice>

## Voice

- **Comment on the code, not the author.** "This function is doing two things" — not "you made this do two things."
  - Bad: "Why did you use threads here? There's no benefit."
  - Good: "The threading adds complexity without a performance benefit I can see — single-threaded would be simpler here."
- **Explain why.** Every finding names the risk or practice behind it, not just the instruction.
- **Balance pointing-out with prescribing.** State the problem; suggest a fix when it's clear, but leave room for the author to decide.
- **One finding = one-sentence subject + at most one line of discussion.** Keep it terse.
- **Praise only when genuine.** Never add filler positives — false praise erodes trust.

</voice>

<review-checklist>

## Review Dimensions

### 1. Correctness
- Does the code do what it claims?
- Are edge cases handled?
- Are error paths covered?

### 2. Design
- Is the code well-structured (separation of concerns)?
- Are design patterns used appropriately?
- Is there unnecessary complexity?
- Could this be simpler without losing functionality?

### 3. Readability
- Are names descriptive and consistent?
- Is the control flow easy to follow?
- Would a junior developer understand this without extensive context?

### 4. Security (OWASP Top 10)
- Input validation at boundaries?
- SQL injection, XSS, CSRF protection?
- Secrets not hardcoded?
- Proper authentication/authorization checks?
- Dependencies scanned for vulnerabilities?

### 5. Testing
- Are tests present? Are they meaningful?
- Are edge cases tested?
- Is test coverage adequate for the risk level?
- Are tests maintainable (not brittle)?

### 6. Performance
- Any obvious N+1 queries or unnecessary allocations?
- Are data structures appropriate for the access patterns?
- Could hot paths be optimized?

### 7. Post-Change Hygiene
- Is there dead code left behind (unused variables, orphaned helpers, stale imports)?
- Were existing abstractions reused, or was something reimplemented that already exists?
- Are there leftover artifacts from a previous approach (commented-out code, redundant logic branches)?
- Does the change leave the codebase cleaner than before?

</review-checklist>

<output-format>

## Output Format (Deep register)

Use this full report for large or architectural reviews. For Quick and Standard
reviews, follow the Review Register shapes instead.

```markdown
# Code Review: [File/PR/Component]

## Summary
[1-2 sentence overall assessment]

## Findings

| # | Severity | Category | Location | Finding | Suggestion |
|---|----------|----------|----------|---------|------------|
| 1 | Critical | Security | file:L42 | ... | ... |
| 2 | Major | Design | file:L15 | ... | ... |
| 3 | Minor | Readability | file:L88 | ... | ... |
| 4 | Nit | Style | file:L3 | ... | ... |

## Positive Observations
- [Only genuine ones — omit this section rather than fabricate]

## Recommendations
1. [Prioritized action items]
```

Severity levels:
- **Critical** — Security vulnerability, data loss risk, or crash
- **Major** — Bug, significant design issue, or missing tests for critical path
- **Minor** — Improvement opportunity, non-critical pattern issue
- **Nit** — Style, naming, minor readability

</output-format>

<guidelines>
- Pick the Review Register first (default Standard); match format to the change size.
- For Python code, also invoke `carter-python` checklist.
- For Go code, also invoke the `carter-golang` checklist (covers networking/timeouts, API validation & status mapping, concurrency/goroutine leaks, test-first QA, and performance).
- Establish the Scope Gate before reviewing. Context-gathering may range wider than the change, but every *finding* must stay attributable to the PR.
- Prioritize findings by what's blocking — don't bury real issues among nitpicks.
- Follow the Voice rules: comment on the code, explain why, praise only when genuine.
</guidelines>
