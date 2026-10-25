# Memory and plans

Carter keeps what it learns, and the work in progress, as plain Markdown files. You
can read, edit or delete any of them. This page covers three things:

- **knowledge**: curated lessons that agents read before they act,
- **memory**: raw notes that may later become knowledge,
- **plans and checkpoints**: multi-session work you can pick up where you left off.

## Two sets of knowledge

| | Workspace knowledge | Global knowledge |
|---|---|---|
| Location | `.carter/knowledge/` in a project | `~/.carter/knowledge/` |
| Created by | `carter init` | `carter install` |
| Applies to | This project only | All your projects |
| Agents read it | First | Second |

The two sets have **different files** on purpose.

**Workspace files** (project facts):

| File | For |
|------|-----|
| `lessons-learned.md` | Lasting lessons. Append only; mark old entries `[SUPERSEDED]` |
| `gotchas.md` | Known issues and workarounds. Remove an entry once it's fixed |
| `tools.md` | Tools, CLIs, MCP servers and how they authenticate here |
| `decisions.md` | Decisions and their reasons |
| `patterns.md` | Conventions this project follows |

**Global files** (lessons that apply everywhere): `decisions.md`, `mistakes.md`,
`patterns.md`, `debugging.md`, `infrastructure.md`, `project-history.md`. Each file
starts with a comment showing its entry format. An entry in `mistakes.md` looks like
this:

```markdown
## 2026-10-25 | Short title
- **Context:** where it happened
- **Mistake:** what went wrong
- **Fix:** what solved it
- **Lesson:** what to do next time
- **Tags:** terraform, auth
```

Rule of thumb: if it is true only for this project, it goes in the workspace. If it
would help in any project, it goes global.

Carter never overwrites knowledge files. `carter init` (workspace) and
`carter install` (global) create them only when they are missing.

### How knowledge gets written

Carter doesn't write knowledge silently. After events like these, Maestro asks
whether to record something:

- a plan is completed,
- a long debugging session ends,
- you correct Carter,
- a new tool turns up.

Say no and it moves on.

## Memory: raw notes

`~/.carter/memories/` is a scratchpad that agents (and you) can write to freely:

```text
~/.carter/memories/
├── user/            notes that apply across projects
├── repo/<name>/     notes about one repository
└── session/         working notes for one conversation
```

Every agent can read `~/.carter/`. Agents with local-write permission can edit
memories without asking.

## From mistake to better agents

Three skills turn notes into improvements. None runs on its own; you ask for each:

1. **Record:** "record this mistake". The `carter-mistakes` skill writes a note to
   memory.
2. **Distill:** "distill my memories". The `carter-distill` skill sorts the notes,
   removes duplicates and adds them to the global knowledge files.
3. **Reflect:** "reflect on recent lessons". The `carter-reflect` skill looks for
   patterns in your knowledge and proposes changes to agents or skills. You approve
   each one.

## Plans

For work that spans sessions, ask for a plan ("plan the OAuth2 migration"). The PM
writes it as a directory:

```text
.carter/state/plans/active/001-oauth2-migration/
├── README.md     goal, definition of done, steps
└── step-01.md    one file per step, when there are more than 3 steps
```

Each plan declares **`must_haves`**, a checkable definition of done: things that
must be true, files that must exist, links to the evidence. Reviews check the work
against them.

A plan's `status` lives in the README's frontmatter (`proposed`, `active`,
`blocked`, `completed`, `abandoned`). Finished or abandoned plans move to
`plans/completed/`. Don't delete plans; mark them `abandoned` so the history stays.

The exact fields are in the [frontmatter reference](../reference/frontmatter.md).

## Session checkpoints

At natural pauses Maestro offers to save a checkpoint: a small file,
`.carter/state/sessions/checkpoint.md`, that points to the active plan and the next
step. At the start of the next session Maestro reads it and tells you where you left
off, so you don't have to explain again.

## Save and validate

```bash
carter save    # commit .carter/ to its private history (recoverable later)
carter check   # validate plans and the checkpoint against their schemas
```

Neither runs automatically. Run `carter check` after editing a plan by hand, and
`carter save` at stopping points (Maestro offers this too).

## Decision records and RFCs

Two skills write design documents into **your project's repository**, because
decisions belong with the code:

- `carter-adr` writes Architecture Decision Records to `docs/adr/`. One decision per
  record; a change of mind is a new record that supersedes the old one.
- `carter-rfc` writes design proposals to `docs/rfcs/`, each reviewed by several
  agents before anything is built.

Ask for them in plain language ("record this decision as an ADR").

## Language

Knowledge, memories, plans, checkpoints, ADRs and RFCs follow the workspace
`docs_language` (default English). Everything else that lands in the repository is
English.

## Next

- [Frontmatter reference](../reference/frontmatter.md)
- [Files and paths](../reference/files-and-paths.md)
