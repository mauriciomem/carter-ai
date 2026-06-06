---
name: carter-docs
description: Write and maintain developer documentation — READMEs, changelogs, API docs, contribution guides — and audit docs for staleness. Use when creating or updating repository documentation.
argument-hint: "[doc type, file, or 'audit' to check for stale/missing docs]"
---

<objective>
Author and maintain repository documentation that developers actually use, and
detect documentation that has gone stale or is missing. Structure content by the
reader's need, not by the shape of the code.
</objective>

<delegation>

## What this skill does NOT do (delegate instead)

This skill authors repo documentation. It does not absorb capabilities that
already exist elsewhere:

| Need | Use instead |
|------|-------------|
| Architecture Decision Records | `carter-adr` |
| Diagrams (Mermaid, architecture) | `carter-diagram` |
| Explaining a topic in chat (not a doc) | `carter-explain` |
| Summarizing *external* docs/standards | `carter-research` |
| Slide decks / Word / PDF deliverables | `pptx` / `docx` / `pdf` |

When a request crosses one of these lines, hand off rather than duplicating.

</delegation>

<diataxis>

## Structure by reader need (Diátaxis)

Every piece of documentation serves one of four needs. Do not mix them in one
document — a tutorial that stops to explain theory, or reference that turns into a
how-to, serves neither reader. Reference: <https://diataxis.fr/>.

| Type | Reader need | Nature | Example |
|------|-------------|--------|---------|
| **Tutorial** | "teach me" | Learning-oriented, a guided lesson | Getting-started walkthrough |
| **How-to guide** | "help me do X" | Task-oriented, a recipe | "How to add an MCP server" |
| **Reference** | "tell me the facts" | Information-oriented, dry & complete | CLI flags, API endpoints, config keys |
| **Explanation** | "help me understand" | Understanding-oriented, discursive | "Why Carter uses a manifest" |

Pick the type first, then write to its need. A README is usually a small tutorial
(quick start) + signposting to the other three.

</diataxis>

<doc-types>

## Documentation Types

### README
- Lead with what it is and the fastest path to value (install → first success).
- Sections, in order: one-line description, install, quick start, key concepts,
  links to deeper docs, contributing, license.
- Keep it skimmable. Push exhaustive detail into reference docs.

### Changelog (Keep a Changelog + Conventional Commits)
- Follow **Keep a Changelog** (<https://keepachangelog.com/>): reverse-chronological,
  an `## [Unreleased]` section, semver headings with dates.
- Group entries under **Added / Changed / Deprecated / Removed / Fixed / Security**.
- Derive entries from **Conventional Commits** (`feat:` → Added, `fix:` → Fixed,
  `feat!:`/`BREAKING CHANGE:` → Changed + a breaking note). Write for humans, not
  raw commit subjects.

### API documentation
- Reference-style: every endpoint/function with parameters, types, return shape,
  errors, and a minimal example. Complete and dry beats narrative here.

### Contribution guide
- How-to oriented: dev setup, how to run tests, branch/commit conventions
  (Conventional Commits), how to open a PR, review expectations.

</doc-types>

<doc-audit>

## Doc-Audit Mode

Detect stale or missing documentation — **git-aware and scoped to the change**,
reusing the Scope Gate discipline from `carter-code-review` (never audit the whole
tree when a diff defines the scope).

### Procedure

1. **Scope.** Determine what changed: `git diff <base>...<head> --name-only`
   (or the PR's changed-file set). Audit docs *related to those changes*, not the
   entire repository, unless a full audit is explicitly requested.
2. **Detect staleness.** For each changed code path, check whether its docs still
   match: renamed flags/commands, changed signatures, moved files, updated config
   keys, version/count numbers that drift (e.g. "6 agents", skill counts).
3. **Detect missing docs.** New public surface (commands, endpoints, config keys,
   exported functions) with no corresponding doc entry.
4. **Detect orphans.** Docs referencing code/paths that no longer exist
   (`git check-ignore` / `git ls-files` to confirm a referenced path is real).
5. **Report** as findings (see Output), each pointing at the doc and the change
   that outdated it.

A finding must be attributable to a real change or a real gap — not a stylistic
preference.

</doc-audit>

<brief-register>

## Brief Register (canonical definition)

Terse, precise, context-aware responses for tickets, PRs, and issues. This is the
**single source of truth** for the Brief register; other skills (`carter-atlassian`,
`carter-ops`) reference it rather than redefining it.

- **Lead with the answer or the ask.** No preamble, no restating the question.
- **One screen, not a page.** Only the context the reader needs to act.
- **Concrete.** Link the file/line/commit; name the exact command or field.
- **Plain.** Short sentences. No filler, no marketing tone.
- **Scoped.** Stay on the ticket/PR at hand; don't editorialize beyond it.

Use Brief for: PR/issue comments, Jira comment bodies, status updates. Use the
fuller doc types above for: READMEs, guides, reference, changelogs.

</brief-register>

<output-format>

## Output Format

When **authoring**, produce the document content directly in the correct Diátaxis
shape — no meta-commentary.

When **auditing**, report findings:

```markdown
# Doc Audit: [scope]

## Summary
[1-2 sentences — overall doc health for the audited scope]

## Findings

| # | Type | Doc | Triggered by | Fix |
|---|------|-----|--------------|-----|
| 1 | Stale | README.md:L12 | `--foo` renamed to `--bar` | Update flag name |
| 2 | Missing | (none) | new `carter sync` command | Add how-to entry |
| 3 | Orphan | docs/old.md:L3 | references deleted `legacy.py` | Remove or update |
```

</output-format>

<guidelines>
- Pick the Diátaxis type before writing; don't mix types in one doc.
- Match detail to the surface: Brief register for ticket/PR replies; full doc
  types for repository documentation.
- Reuse existing docs and abstractions — update in place rather than duplicating.
- Cite conventions you follow (Diátaxis, Keep a Changelog, Conventional Commits).
- Delegate per the table above; never reimplement ADRs, diagrams, or binary docs.
</guidelines>
