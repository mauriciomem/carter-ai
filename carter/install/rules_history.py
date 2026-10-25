# ruff: noqa: E501 — historical texts are kept byte-exact, one source line per text line.
"""Every global rules text (``~/.config/opencode/AGENTS.md``) Carter has shipped.

An installed file byte-identical to one of these is unmodified Carter content and is
upgraded in place; anything else is treated as user-modified and never touched.
Recovered from git history; append the outgoing text whenever the rules change.
"""

SHIPPED_GLOBAL_RULES: tuple[str, ...] = (
    # v0.1.0, root install.py (Copilot-era)
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `/memories/`.\n"
        "- Consult `~/.copilot/knowledge/` before proposing solutions to check for past decisions and lessons.\n"
    ),
    # v0.1.0, single-line memory rules
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `~/.carter/memories/` (visible) and `/memories/` (platform, if available).\n"
        "- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for project-specific notes, and `session/` for conversation-scoped working notes.\n"
        "- Consult `~/.carter/memories/` and `~/.copilot/knowledge/` before proposing solutions to check for past decisions and lessons.\n"
    ),
    # v0.1.0..v0.7.x, wrapped memory rules
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow\n"
        "its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `~/.carter/memories/` (visible) and\n"
        "  `/memories/` (platform, if available).\n"
        "- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for\n"
        "  project-specific notes, and `session/` for conversation-scoped working notes.\n"
        "- Consult `~/.carter/memories/` and `~/.copilot/knowledge/` before proposing\n"
        "  solutions to check for past decisions and lessons.\n"
    ),
    # v0.8.0, + Communication
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow\n"
        "its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `~/.carter/memories/` (visible) and\n"
        "  `/memories/` (platform, if available).\n"
        "- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for\n"
        "  project-specific notes, and `session/` for conversation-scoped working notes.\n"
        "- Consult `~/.carter/memories/` and `~/.copilot/knowledge/` before proposing\n"
        "  solutions to check for past decisions and lessons.\n"
        "\n"
        "## Communication\n"
        "- Be concise and clear. Explain so a junior developer or solution architect understands.\n"
        "- Cite sources. State which documentation, standards, or references inform your answers.\n"
        "- When reviewing, match detail to the change (quick vs deep), comment on the code not the author, and explain *why* behind each finding. See `carter-code-review`.\n"
        "- At any doubt, ask for clarification before proceeding.\n"
    ),
    # v0.10.0, + Git & Language
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow\n"
        "its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `~/.carter/memories/` (visible) and\n"
        "  `/memories/` (platform, if available).\n"
        "- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for\n"
        "  project-specific notes, and `session/` for conversation-scoped working notes.\n"
        "- Consult `~/.carter/memories/` and `~/.copilot/knowledge/` before proposing\n"
        "  solutions to check for past decisions and lessons.\n"
        "\n"
        "## Communication\n"
        "- Be concise and clear. Explain so a junior developer or solution architect understands.\n"
        "- Cite sources. State which documentation, standards, or references inform your answers.\n"
        "- When reviewing, match detail to the change (quick vs deep), comment on the code not the author, and explain *why* behind each finding. See `carter-code-review`.\n"
        "- At any doubt, ask for clarification before proceeding.\n"
        "\n"
        "## Git & Language\n"
        "- You (the user) are always the commit author and sign with your own key. Never pass `--author`; credit Carter only with a trailer: `Co-authored-by: <name> <email>` from `[attribution]` in `~/.carter/config.toml` (default `carter-bot <carter-bot@users.noreply.github.com>`).\n"
        "- Everything that lands in a repository or leaves the workspace is written in English, whatever language the conversation uses: commit messages, branch names, code comments, repo docs, PR/issue titles and bodies, review comments, release notes, Jira and Slack text.\n"
        "- Carter's internal docs (ADRs, RFCs, `.carter/` plans/knowledge/checkpoints, memories) use the workspace `docs_language` from `.carter/carter.yaml`; without one, English unless the user asks for another language.\n"
        "- Talk to the user in their own language.\n"
    ),
    # v0.11.0 legacy base (~/.carter/knowledge)
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow\n"
        "its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `~/.carter/memories/` (visible) and\n"
        "  `/memories/` (platform, if available).\n"
        "- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for\n"
        "  project-specific notes, and `session/` for conversation-scoped working notes.\n"
        "- Consult `~/.carter/memories/` and `~/.carter/knowledge/` before proposing\n"
        "  solutions to check for past decisions and lessons.\n"
    ),
    # v0.11.0 legacy + Communication
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow\n"
        "its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `~/.carter/memories/` (visible) and\n"
        "  `/memories/` (platform, if available).\n"
        "- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for\n"
        "  project-specific notes, and `session/` for conversation-scoped working notes.\n"
        "- Consult `~/.carter/memories/` and `~/.carter/knowledge/` before proposing\n"
        "  solutions to check for past decisions and lessons.\n"
        "\n"
        "## Communication\n"
        "- Be concise and clear. Explain so a junior developer or solution architect understands.\n"
        "- Cite sources. State which documentation, standards, or references inform your answers.\n"
        "- When reviewing, match detail to the change (quick vs deep), comment on the code not the author, and explain *why* behind each finding. See `carter-code-review`.\n"
        "- At any doubt, ask for clarification before proceeding.\n"
    ),
    # v0.11.0..v0.12.0, + Git & Language
    (
        "# Carter — Global Rules\n"
        "\n"
        "When the user's request starts with `ops:`, load the `carter-ops` skill and follow\n"
        "its instructions exactly.\n"
        "\n"
        "## Memory\n"
        "- Record mistakes and key learnings to `~/.carter/memories/` (visible) and\n"
        "  `/memories/` (platform, if available).\n"
        "- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for\n"
        "  project-specific notes, and `session/` for conversation-scoped working notes.\n"
        "- Consult `~/.carter/memories/` and `~/.carter/knowledge/` before proposing\n"
        "  solutions to check for past decisions and lessons.\n"
        "\n"
        "## Communication\n"
        "- Be concise and clear. Explain so a junior developer or solution architect understands.\n"
        "- Cite sources. State which documentation, standards, or references inform your answers.\n"
        "- When reviewing, match detail to the change (quick vs deep), comment on the code not the author, and explain *why* behind each finding. See `carter-code-review`.\n"
        "- At any doubt, ask for clarification before proceeding.\n"
        "\n"
        "## Git & Language\n"
        "- You (the user) are always the commit author and sign with your own key. Never pass `--author`; credit Carter only with a trailer: `Co-authored-by: <name> <email>` from `[attribution]` in `~/.carter/config.toml` (default `carter-bot <carter-bot@users.noreply.github.com>`).\n"
        "- Everything that lands in a repository or leaves the workspace is written in English, whatever language the conversation uses: commit messages, branch names, code comments, repo docs, PR/issue titles and bodies, review comments, release notes, Jira and Slack text.\n"
        "- Carter's internal docs (ADRs, RFCs, `.carter/` plans/knowledge/checkpoints, memories) use the workspace `docs_language` from `.carter/carter.yaml`; without one, English unless the user asks for another language.\n"
        "- Talk to the user in their own language.\n"
    ),
)
