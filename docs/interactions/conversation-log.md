# Carter — Design Conversation Log

> Captured: May 9, 2026
> Participants: User (mmitolo), GitHub Copilot (grill-me skill)

---

## Q1: What is the orchestration runtime?

**Options presented:**
1. VS Code agent system (declarative markdown)
2. Custom Python/Go application (LangChain, LangGraph, etc.)
3. OpenCode CLI plugin architecture
4. Hybrid — VS Code agent system + CLI via shared instruction files

**Recommendation:** Option 4 (Hybrid), anchored on VS Code's native agent system. The `.agent.md` / `SKILL.md` / `.instructions.md` system gives orchestration, personality routing, tool restrictions, and MCP server bindings declaratively, with no custom runtime. Same files work across VS Code and CLI.

**Decision:** Agreed. Hybrid it is.

---

## Q2: How should the orchestrator route to domain personalities?

**Options presented:**
1. Single orchestrator agent with skills
2. Separate agents, no orchestrator (user picks explicitly)
3. Orchestrator agent that spawns sub-agents
4. Orchestrator + direct access (both routed and direct invocation)

**Recommendation:** Option 4. Matches the user's requirement of "can use the orchestration, or directly use a specific knowledge or tools." Each personality is a standalone `.agent.md` plus the orchestrator delegates via `runSubagent`.

**Decision:** Agreed. Orchestrator + direct access.

---

## Q3: Where should the agent files live?

**Options presented:**
1. User-level only (`~/.copilot/`)
2. Workspace-level only (per-repo)
3. User-level agents + workspace-level overrides

**Recommendation:** Option 3. Personalities are general-purpose (user-level), but projects can layer on specific conventions. Standardize on `~/.copilot/` as the root.

**Decision:** Agreed. User-level at `~/.copilot/` with workspace-level overrides.

---

## Q4: How should the "Learner" personality's memory work?

**Options presented:**
1. Copilot memory system only (`/memories/`)
2. Dedicated knowledge base files in `~/.copilot/knowledge/`
3. Git-backed knowledge repo
4. Hybrid — `/memories/` for fast capture + structured knowledge files for curated learnings

**Recommendation:** Option 4. Two-tier: fast capture via `/memories/`, curated via `~/.copilot/knowledge/`. A "distill" skill promotes valuable learnings. Git-backing deferred to v2.

**Decision:** Agreed. Hybrid memory with on-demand distill.

---

## Q5: Which MCP servers should be included?

**Options discussed:**
- v1 candidates: GitHub, Terraform/HCP, Atlassian, AWS, Vault, Boundary, Packer
- Scoping: all-access vs per-agent restrictions

**Recommendation:** v1 servers: GitHub, Terraform/HCP, Atlassian. Per-agent tool restrictions (least privilege). AWS and Vault deferred to v2 (larger blast radius).

**Per-agent scoping:**
- Maestro: No MCP access (delegates)
- Architect: GitHub (read), Terraform (read)
- Engineer: GitHub (full), Terraform (read)
- DevOps: GitHub (full), Terraform (full)
- Learner: Confluence (read)
- PM: Jira (full), Confluence (full), GitHub (read)

**Decision:** Agreed.

---

## Q6: What skills should each personality agent have?

**Proposed full skill map across all agents.** User expanded v1 beyond the initial recommendation.

**v1 skills agreed:**
- Maestro: `triage`, `distill`
- Architect: `design-review`, `diagram`, `adr`
- Engineer: `code-review`, `test-first`
- DevOps: `pipeline`, `terraform`, `git-strategy`
- Learner: `explain`, `mistakes`, `research`
- PM: `plan`, `risk`
- Plus: Python skill and Golang skill (next question)

**Decision:** Agreed with user's additions.

---

## Q7: Where do the Python and Golang skills belong?

**A) Ownership:**
1. Software Engineer only
2. Shared across Engineer and DevOps
3. Standalone agents

**Recommendation:** Option 2 (Shared). Skills live as standalone `SKILL.md` files referenced by both Engineer and DevOps agents.

**B) Scope:** Each skill is a coding standards reference + enforcement checklist covering: project structure, design patterns, testing, security, code quality, error handling, concurrency, dependency management, extensibility. Based on PEP 8, Effective Go, Google style guides.

**Decision:** Agreed on both A and B.

---

## Q8: How should the installer work?

**A) Installer steps:** Detect OS, create directories, copy files, configure MCP, initialize knowledge, validate prerequisites, print summary. Plus `--uninstall` flag with manifest-based cleanup.

**B) Backup strategy:** Merge with backup. Back up existing files to `~/.copilot/backup/<timestamp>/`, write new files. Manifest tracks Carter-owned files.

**C) Packaging:** Single `install.py` using `uv run`.

**User feedback:**
- Must work with Copilot and OpenCode
- Easy install/uninstall for both
- Python 3.11+ minimum
- Use `uv` natively, as many features as possible
- Add planning for future packaging (distributable tool)

**Decision:** Agreed with user's additions.

---

## Q9: How should the installer handle Copilot vs OpenCode file placement?

**Options presented:**
1. Shared source, dual output with `--target` flag
2. Symlink strategy
3. Single canonical location with adapters

**Recommendation:** Option 1. Most reliable — no symlink fragility. Installer renders same content into both formats. `--target all` default, `--target copilot`/`--target opencode` specific.

**Decision:** Agreed.

---

## Q10: How should the installer's CLI output work?

**Verbosity levels:** `--quiet`, default, `--verbose`, `--debug`

**Output style:**
- Option 1: ANSI escape codes, stdlib only
- Option 2: `rich` library (progress bars, tables, trees, panels, spinners)

User asked to see Option 2 example — was shown full output with tables, tree views, progress bars, panels, and "Next steps" section.

User asked if the installer could include `rich` install — answer: yes, via `uv run --with rich` or PEP 723 inline dependencies.

**Decision:** Go with Option 1 (ANSI/stdlib) for v1. Option 2 is a documented v2 upgrade path.

---

## Q11: What is the project repository structure?

**Full repo layout proposed** with: `install.py`, `install.sh`, agents/, skills/, knowledge/, mcp/, instructions/, docs/, tests/.

**User feedback:** Named the project "Carter".

**Decision:** Agreed. Project name: Carter.

---

## Q12: How should MCP server configurations be merged?

**Options presented:**
1. Deep merge on MCP key only
2. Append-only with conflict detection
3. Namespaced keys with overwrite (`carter-` prefix)

**Recommendation:** Option 3. `carter-` prefix creates clear ownership boundary. Installer freely updates `carter-*` entries, never touches others. Warns when non-prefixed duplicates exist.

User asked for clarification on coexistence (e.g., `github` and `carter-github` side by side) — explained that both servers run independently, agents with tool restrictions only see their scoped server, and the installer warns but never modifies the user's entry.

**Decision:** Agreed.

---

## Q13: Should Carter have an `--update` mechanism?

**Options presented:**
1. Re-run installer (idempotent)
2. Explicit `--update` flag with hash comparison
3. Git-pull + re-install
4. Self-updating (auto git pull)

**Recommendation:** Option 3 with Option 2's diff behavior built in. `git pull && uv run install.py` — installer compares hashes, only updates changed files, reports per-file status.

User reminded that `uv` should be the primary invocation method.

**Installer invocation finalized:** `uv run install.py` with PEP 723 inline metadata (`requires-python = ">=3.11"`). `uv` handles Python resolution automatically.

**Decision:** Agreed. `uv run install.py` is the canonical method.

---

## Q14: What goes in the global `copilot-instructions.md`?

**Proposed content (~25 lines):**
1. Identity ("You are Carter")
2. Communication style (concise, cite sources, junior-friendly)
3. Ask-before-act
4. Memory protocol
5. Token efficiency
6. Security baseline (OWASP)
7. Test-first default
8. Technology preferences

Per-agent personality stays in each `.agent.md`.

**Decision:** Agreed.

---

## Q15: How does Maestro decide which agent to route to?

**Options presented:**
1. Keyword matching table
2. Two-pass classification
3. Intent classification with multi-agent chaining

**Recommendation:** Option 3. Maestro classifies and can chain agents sequentially for multi-domain tasks. Includes a routing table with domain/agent/trigger mappings. If uncertain, asks the user.

**Decision:** Agreed.

---

## Q16: How should knowledge base files be structured?

**A) Format:** Structured entries with date, context, details, tags (not flat append-only).

**B) Distill workflow:** On-demand skill that reads `/memories/`, classifies, deduplicates, appends to knowledge files, suggests cleanup.

**Decision:** Agreed.

---

## Q17: How does Carter map to OpenCode's configuration model?

**Options presented:**
1. Full parity with translation layer
2. Copilot-first, OpenCode-lite
3. Copilot-first v1, full OpenCode v2

**Recommendation:** Option 3 (Copilot-first, OpenCode-lite in v1).

**Decision:** User overrode — wants full parity in v1.

---

## Q18: What version of OpenCode, and what's the config format?

**Investigation:** Explored `~/.config/opencode/` on the user's machine. Found:
- `opencode.json` with MCP config
- `agents/` directory with `.md` files using YAML frontmatter
- `skills/` directory with `SKILL.md` files

**Key finding:** OpenCode's format is very close to Copilot's — both use markdown + YAML frontmatter. Translation layer is simpler than expected.

---

## Q19: OpenCode agent `model`, `temperature`, and `mode` settings?

**Recommendation:** Don't hardcode models — use `${CARTER_MODEL}` placeholder. Per-agent temperatures: Maestro 0.2, Architect 0.4, Engineer 0.1, DevOps 0.1, Learner 0.3, PM 0.2. Only Maestro gets `mode: primary`.

**Decision:** Agreed.

---

## Q20: How should the installer handle MCP server credentials?

**Options presented:**
1. Env var references
2. Interactive prompt during install
3. Env vars with validation
4. Vault integration

**Recommendation:** Option 3. Installer checks env vars at install time, warns on missing with setup instructions, writes configs with variable references (never raw tokens). Ships `.env.example`.

**Decision:** Agreed.

---

## Q21: How should the installer be tested?

**v1:** pytest unit tests with `tmp_path` + snapshot/golden file tests. Installer accepts `--base-dir` to redirect writes. Run with `uv run --with pytest pytest tests/`.

**v2:** Docker-based integration tests in CI. Clean install, upgrade, uninstall, MCP merge, credential validation. GitHub Actions matrix.

**User feedback:** Extend v2 details in the plan for future reference.

**Decision:** Agreed. v2 testing details expanded in plan.

---

## Q22: What is the implementation order?

**Four phases agreed:**
1. Foundation — repo, global instructions, Maestro, installer v0
2. Agents + Skills — all 6 agents, all 17 skills
3. Infrastructure — MCP configs, installer v1, knowledge base
4. Polish — tests, README, `.env.example`

**Decision:** Agreed.

---

## Q23: Should Carter's files use the `carter-` prefix?

**Options presented:**
1. Prefixed filenames (`carter-maestro.agent.md`)
2. Unprefixed (`maestro.agent.md`)
3. Subdirectory (`carter/maestro.agent.md`)

**Recommendation:** Option 1. Consistent with MCP naming. User invokes as `@carter-maestro`, `@carter-devops`, etc.

**Decision:** Agreed.

---

## Q24: How does Carter work with Copilot CLI?

**Initial assumption was wrong** — assumed `gh copilot` (limited tool). User clarified it's the standalone `copilot` CLI v1.0.44 at `/opt/homebrew/bin/copilot`.

**Investigation:** Full-featured agentic tool supporting `--agent`, skills, MCP servers. Uses **same `~/.copilot/` directory** as VS Code. Agents and skills are shared natively.

**Revised mapping:**
- VS Code + Copilot CLI share `~/.copilot/` (agents, skills)
- Only MCP config differs: VS Code uses `settings.json`, Copilot CLI uses `copilot mcp add` commands
- OpenCode remains separate target at `~/.config/opencode/`

**Installer targets finalized:**
- `--target copilot` → writes to `~/.copilot/` + configures MCP for VS Code AND Copilot CLI
- `--target opencode` → writes to `~/.config/opencode/`
- `--target all` → both (default)

**Decision:** Agreed.

---

## Q25: What is the MCP config format for Copilot CLI?

**Investigation:** Ran `copilot mcp --help` and `copilot mcp add --help`. Discovered the CLI has its own `mcp add`/`remove` commands for managing `~/.copilot/mcp-config.json`.

**Recommendation:** Use `copilot mcp add carter-*` commands (not direct file write). Forward-compatible, idempotent. Uninstall uses `copilot mcp remove carter-*`.

**MCP config methods per target:**
- VS Code: JSON merge into `settings.json`
- Copilot CLI: `copilot mcp add` / `copilot mcp remove`
- OpenCode: JSON merge into `opencode.json`

**Decision:** Agreed.

---

## Q26: Any remaining concerns?

**Full decision summary reviewed (22 items).** No outstanding issues.

**Decision:** Proceed to plan output.
