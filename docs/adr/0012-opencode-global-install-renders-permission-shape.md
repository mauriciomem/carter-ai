---
id: ADR-0012
status: accepted
created: 2026-06-29
decided: 2026-06-29
supersedes: []
superseded_by: null
rfc: null
tags: [install, opencode, agents, tools, permission, global]
---

# ADR-0012: `carter install` renders OpenCode-shaped agents for the opencode target

**Status:** Accepted
**Date:** 2026-06-29
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Related:** Follows [ADR-0011](0011-tools-allowlist-derives-from-policy.md) (which
populated every agent's copilot `tools:` array) and [ADR-0010](0010-agent-platform-refresh.md)
§D4 (per-target native enforcement: copilot `tools:` vs opencode `permission`).

---

## Context

`carter install` installs the global agent set into `~/.copilot/agents/` **and**
`~/.config/opencode/agents/`. `install_agents` copied the **same** static
`agents/carter-*.md` file to both targets.

The static `agents/*.md` are **copilot-shaped**: a `tools:` allowlist **array**
(`[codebase, search, …]`), `agents:`/`handoffs:`, and a display-name `model:`
(`Claude Opus 4.8`). OpenCode's frontmatter schema is different — it uses a
`permission` block, a `provider/model` id (`anthropic/claude-opus-4-8`), and treats
`tools:` as a deprecated **object** (`{name: bool}`), never an array.

Copying the copilot file into `~/.config/opencode/` was therefore always wrong, but
it was *tolerated* while the arrays were small/empty. [ADR-0011](0011-tools-allowlist-derives-from-policy.md)
populated every agent's `tools:` array, which turned the latent mismatch into a hard
**parse failure** — a fresh `opencode` CLI on Linux rejects the install:

```
Configuration is invalid at ~/.config/opencode/agents/carter-pm.md
↳ Expected object | undefined, got ["codebase","search",…] tools
```

Carter already *renders* correct OpenCode frontmatter (`render_agents` with
`target="opencode"` produces the `permission` block). The installer simply did not
use it for the global install.

## Decision

**For the opencode target, `carter install` renders OpenCode-shaped agent frontmatter
from the shipped guarded defaults instead of copying the copilot static file.** The
copilot target is unchanged (it still copies the static `agents/*.md`).

- A new `_install_rendered_file(content, dst, …)` installs already-rendered content
  with the same backup/manifest/hash semantics as `_install_file` (and uses the
  `sha256:`-prefixed hash so the re-install unchanged-check actually matches).
- `install_agents` renders the opencode set once via `render_agents` over
  `generate_default_config(...)` with `target="opencode"`, canonical names (no agent
  suffix — global installs use `carter-<role>.md`), and writes each through
  `_install_rendered_file`.
- The render import is lazy, so the install path pulls in the Jinja/scaffold stack
  only when an opencode target is requested.

The global install thus matches each runtime's native schema: copilot gets the
`tools:` allowlist (ADR-0011), opencode gets the `permission` block (ADR-0010 §D4).

## Consequences

**Positive**

- `opencode` accepts the global install — the parse failure is fixed at the source.
- Each target receives its schema-correct frontmatter; no runtime silently ignores or
  rejects keys meant for the other.
- A regression test asserts opencode agents carry `permission` + a `provider/model` id
  and **no `tools` array**, and that copilot agents keep their array — so neither
  shape can drift back.

**Negative / accepted**

- The installer now depends on the scaffold/render stack for opencode (previously a
  pure file copy). Accepted: it is the single source of correct per-target frontmatter,
  and the import is lazy.
- Global opencode agents are rendered from the **guarded defaults**, not a workspace
  `carter.yaml` (there is none at global scope) — consistent with the copilot statics,
  which are the baked guarded defaults (ADR-0005 D6 / ADR-0002).

## See also

- [ADR-0011](0011-tools-allowlist-derives-from-policy.md) — populated the copilot
  `tools:` array that surfaced this.
- [ADR-0010](0010-agent-platform-refresh.md) §D4 — copilot `tools:` vs opencode
  `permission` as the per-target native enforcement surfaces.
- [OpenCode agents docs](https://opencode.ai/docs/agents/) — `permission` schema;
  `tools` is a deprecated object, never an array.
