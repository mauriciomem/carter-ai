# Implementation Plan — Revision Questions

> Questions and challenges to apply to `implementation-plan.md` before execution.
> Organized by the user's stated preferred features.

---

## A. Quality Gates with Iteration

The current plan (Phase 4) proposes "ONE review round + ONE fix cycle." The fresh assessment suggests 2 rounds minimum is more defensible.

### Questions to Resolve

1. **What triggers the gate?** The plan says "before any push or PR creation." But Carter doesn't intercept `git push`. Is the trigger:
   - User explicitly asks Carter to push (via carter-ops)?
   - User asks for a review before pushing (on-demand)?
   - Carter-maestro detects code changes and proactively offers review?
   - All three, with different gate strictness levels?

2. **What's "clean"?** The plan says "if blocking findings exist → fix and re-review." But:
   - Does "clean" mean zero blocking findings only? Or zero findings period?
   - Should known issues (already in `gotchas.md`) be excluded from the count?
   - Should `must_haves` satisfaction be a separate pass/fail from code review?

3. **Should Carter inject `must_haves` into reviewer context?** Yui does this explicitly. The current plan mentions `must_haves` but doesn't specify HOW they reach the reviewer. Should the plan add: "Maestro reads plan must_haves and includes them in every review agent prompt"?

4. **Scope scaling**: The plan has a table (code push <5 files → engineer only, 5-15 → + architect). But:
   - Is file count actually a good proxy for review scope?
   - Should changed-line count or module boundaries matter more?
   - What about refactors that touch 20 files but change zero behavior?

5. **Cost/latency budget**: Multi-agent parallel review with 2 rounds = 4-10 subagent calls per push. The plan never addresses:
   - What's the acceptable latency for a quality gate?
   - Should there be a "fast gate" (engineer only, 1 round) vs. "full gate" (multi-agent, 2 rounds)?
   - Can the user choose gate level per push?

---

## B. Filesystem-as-Memory

The current plan (Phase 1 + 3) proposes `.carter-state/` with plans/sessions directories. Fresh assessment challenges whether this is the right structure.

### Questions to Resolve

6. **Git or no git for state?** Yui uses local git repos for `.plans/` and `.knowledge/`. The current plan says "Do NOT require git repos (overhead for casual use)." But:
   - Without git, how do you roll back a corrupted plan?
   - Without git, how do you see what changed between sessions?
   - Is `git init && git add -A && git commit -m "checkpoint"` really "overhead"? It's two commands.
   - Counter: optional git (`carter init --git-state`)?

7. **Where does `.carter-state/` live in umbrella mode?** The plan says "workspace root." But:
   - In umbrella mode, the root IS the umbrella (not a git repo). State lives there naturally.
   - In single-repo mode, `.carter-state/` is inside the project. `.gitignore` it — but it still clutters.
   - Should single-repo mode use `~/.carter/state/<workspace-hash>/` instead?

8. **Session checkpoint format**: The plan proposes `sessions/checkpoint.md` for "last session's final state." But:
   - What actually goes in this file? The conversation summary? Active plan status? Both?
   - Who writes it? Carter at session end? The platform automatically?
   - VS Code Copilot already persists conversation summaries. Does this duplicate that?
   - What if the session ends abruptly (user closes VS Code)? Is the checkpoint stale?

9. **Knowledge file size limits**: The plan says "soft limit 500 lines." But:
   - What happens at 500 lines? Archive? Split?
   - How does Carter handle a `lessons-learned.md` that's too large for context?
   - Should knowledge files be loaded selectively (only relevant sections) rather than entirely?

---

## C. Template-Driven Agent Generation (Jinja2)

The current plan does NOT propose template-driven generation. This is a NEW feature to add.

### Questions to Resolve

10. **What's the `carter init` command?** Proposed interface:
    ```
    carter init [--umbrella] [--config config.yaml] [target-dir]
    ```
    - Should this be a Python CLI? Or a VS Code Copilot command?
    - What's the minimum config? Just `workspace_name` and `git_account`?
    - How does it detect existing Carter installations?

11. **What's templated vs. hand-crafted?**
    - Agent files → templated (consistent structure, configurable roster)
    - Skill files → hand-crafted (complex, unique logic per skill)
    - Instructions → templated (workspace-specific fields)
    - Knowledge files → template for initial creation, hand-maintained after
    - Carter-ops → hand-crafted (deterministic operations)

12. **Jinja2 template inheritance**: Should there be a base agent template?
    ```
    {# base_agent.md.j2 #}
    ---
    {{ frontmatter | to_yaml }}
    ---
    <identity>
    {{ identity }}
    </identity>
    <role>
    {% block role %}{% endblock %}
    </role>
    <boundaries>
    {% block boundaries %}{% endblock %}
    </boundaries>
    ```
    This eliminates duplication across agents. Yui couldn't do this with Handlebars — Jinja2 can.

13. **Config schema**: What fields does Carter's config need?
    - `workspace_name`, `workspace_description`
    - `git_account`, `github_org` (optional)
    - `agents` (list of agents to generate — subset selection)
    - `personality` (skeptical/helpful/pragmatic)
    - `tools` (MCP servers available)
    - `mode` (umbrella/single-repo)
    - `quality_gate_level` (off/light/full)
    - `redaction_enabled` (boolean)
    - `tdd_strict` (boolean — enforce spec-first or allow iterative)

14. **`carter update` semantics**: What happens when:
    - New agent templates are added to Carter? → `carter update` adds them
    - User has modified agent files by hand? → Preserve? Overwrite? Merge?
    - Strategy: Yui overwrites templated files but preserves `.knowledge/`. Same for Carter?
    - Should modified files get a header `# GENERATED — edits will be lost on update`?

---

## D. Umbrella Workspace (Optional)

The current plan proposes `.carter-state/` in workspace root but doesn't fully design umbrella mode.

### Questions to Resolve

15. **What does `carter init --umbrella` actually create?**
    ```
    umbrella-workspace/
    ├── .carter/
    │   ├── config.yaml        ← workspace config
    │   ├── agents/            ← generated agent files
    │   ├── instructions/      ← generated instructions
    │   ├── knowledge/         ← curated knowledge (git-tracked)
    │   ├── plans/             ← execution state (git-tracked)
    │   └── templates/         ← custom template overrides
    ├── project-a/             ← git repo
    └── project-b/             ← git repo
    ```
    Or should agents live at project level (`.github/agents/`) and only state lives at umbrella level?

16. **How does Carter know it's in umbrella mode?** Detection:
    - Presence of `.carter/config.yaml` at a parent directory?
    - Explicit `mode: umbrella` in config?
    - Both? Config takes precedence, parent traversal as fallback?

17. **Project-specific overrides in umbrella mode**: Can individual projects override the umbrella config? E.g., project-a uses strict TDD but project-b is experimental.

---

## E. TDD Development Focused

The current plan keeps TDD as-is (carter-engineer handles it). Fresh assessment suggests stronger integration.

### Questions to Resolve

18. **Should carter-engineer split into test-writer and implementer?** Yui splits Shin (tests) from Kou (code). The plan rejected this split ("carter-engineer handles both"). But:
    - Does the separation actually improve quality? (Evidence: Yui's tests are well-structured)
    - Is the overhead of 2 subagent calls worth it for strict red→green discipline?
    - Compromise: carter-engineer writes `@spec-handoff` first, then implements — single agent, same discipline?

19. **When is TDD mandatory vs. optional?** The plan inherits Yui's skip criteria. But:
    - Who decides? Carter-maestro before delegation? Carter-engineer self-assesses?
    - Should the plan explicitly mark steps as "TDD required" vs. "TDD optional"?
    - Is there a config flag (`tdd_strict: true`) that overrides per-step decisions?

20. **`@spec-handoff` format for Carter**: Should Carter formalize this? Proposed:
    ```python
    # @spec-handoff
    # @interface: FunctionName(arg: Type) -> ReturnType
    # @behavior:
    #   - When X, returns Y
    #   - When Z, raises ValueError
    # @edge-cases:
    #   - Empty input → returns []
    #   - None input → raises TypeError
    ```

---

## F. Redaction System

The current plan explicitly SKIPS redaction ("Carter is personal/team use, not public-facing"). The user now wants it. This reverses a prior decision.

### Questions to Resolve

21. **Scope**: Where does redaction apply?
    - Only a dedicated "storyteller/external" agent? (Yui's approach)
    - Cross-cutting: any agent producing output for external systems (Jira, Slack, GitHub PRs)?
    - Both: dedicated agent for narratives + lightweight check for all external output?

22. **Which categories apply to Carter?** Of Yui's 9:
    - ✅ Secrets (always relevant)
    - ✅ PII (relevant for Jira/Slack output)
    - ⚠️ Employee data (relevant for team use, less for personal)
    - ❌ Project codenames (maybe irrelevant for personal)
    - ⚠️ Legal/compliance (relevant for work contexts)
    - ✅ Internal hostnames/URLs (relevant — Carter accesses internal systems)
    - ⚠️ Financial figures (relevant for work, not personal)
    - ❌ M&A/partnerships (likely irrelevant)
    - ✅ Security incident details (always relevant)
    - **Proposed Carter set**: Secrets, PII, Internal URLs, Security incidents (mandatory). Employee data, Legal, Financial (opt-in per workspace).

23. **Anti-bypass clause**: Should Carter adopt the full anti-bypass clause? Considerations:
    - Pro: It's the strongest prompt-injection defense available without code
    - Con: It's aggressive — could refuse legitimate requests if too broad
    - Compromise: Adopt for external-facing output only, not for internal working documents

24. **Implementation**: Is redaction a skill (loaded on demand) or baked into agent instructions?
    - Skill approach: `carter-redact` skill loaded when producing external output
    - Baked-in approach: All agents have a `<redaction_check>` block for external actions
    - Hybrid: Maestro adds redaction check to delegation prompts when target is external

---

## G. Personality: Skeptical, Reviewer, Question-Focused

The current plan doesn't address personality changes. This is new.

### Questions to Resolve

25. **Where does personality live?** Options:
    - `<identity>` block in each agent → consistent skepticism everywhere
    - Only in maestro → specialists remain neutral
    - Only in architect + reviewer agents → skepticism where it adds most value
    - Global instruction (`instructions/copilot-instructions.md`) → applies to all

26. **What does "skeptical" look like in practice?**
    - Questions before accepting requirements at face value?
    - Challenging assumptions in designs?
    - Pushing back on user requests that seem risky?
    - All of the above?
    - Specific phrases: "What happens when...", "Have you considered...", "What's the evidence for...", "What's the failure mode?"

27. **How skeptical is TOO skeptical?** If Carter questions everything:
    - Does it slow down trivial tasks? (User says "add a print statement" → Carter: "But what's your hypothesis?")
    - Is there a "trust threshold" below which Carter just executes?
    - Should skepticism scale with task complexity? (Trivial → just do it. Multi-file → question first.)

28. **Interaction with existing "ask before acting on ambiguity" rule**: Carter already has this. The delta is:
    - Current: ask when ambiguous
    - Proposed: ask + challenge even when clear, if the request seems risky or under-specified
    - How to distinguish "healthy skepticism" from "annoying over-questioning"?

---

## H. Cross-Cutting Questions

29. **Phase ordering given new preferences**: The current plan is Phase 0-6. With the new features, should it be:
    - Phase 0: Template system + `carter init` (enables everything else)
    - Phase 1: Quality gates with iteration (highest stated priority)
    - Phase 2: Filesystem-as-memory + umbrella mode
    - Phase 3: TDD strengthening + spec-handoff
    - Phase 4: Redaction system
    - Phase 5: Personality/skepticism integration
    - Phase 6: Boundary enforcement + new agents

30. **Token budget**: Adding quality gates, redaction rules, TDD instructions, personality, and boundaries to agent files significantly increases their token count. Has anyone measured:
    - Current carter-maestro.md token count?
    - Estimated after-implementation token count?
    - VS Code Copilot's effective context budget for agent instructions?

31. **Validation strategy**: How do we know each phase works? The devil's advocate review correctly identified the lack of testing methodology. Proposed:
    - Phase validation = 3 real-use sessions with the new behavior
    - Record any friction points in `gotchas.md`
    - If friction > benefit in those 3 sessions → revert or adjust before proceeding

32. **Minimum viable implementation**: Instead of 6-7 phases, what's the fastest path to a working prototype that includes ALL preferred features (quality gates, filesystem memory, templates, umbrella, TDD, redaction, skeptical personality)? Could a single focused day produce a "v0.1" that validates the concept?

---

*Prepared: 2026-05-29*
