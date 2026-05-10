
## skill refinements

1. Refine and extend the carter-terraform skill. The main source references for improvements are the external/agent-skills/terraform/code-generation and external/agent-skills/terraform/module-generation folders. Don't use everything; take into account our existing conversation and context (for example, we don't need the azure-verified-modules folder to review).

2. In general, for this skill and others that may come next, the main skill/tool (terraform, aws, packer, python, etc.) should be the primary skill and can have one or more references or source maps inside the main skill folder. Take this idea, analyze it, and look up best practices, then update the plan v2 files with the processed idea.

3. Create a new carter-packer skill for HashiCorp Packer. The main source reference for the skill is external/agent-skills/packer. Don't use everything; take into account our existing conversation and context.

4. Modify the carter-pipeline entirely. The skill should be used for Git and GitHub operations. Git command best practices (add, commit, merge, branch, fetch, pull, push, etc.). GitHub CLI best practices (gh). Use external/engineering-agent-skills/skills/gh as a source of reference. The existing carter-pipeline and carter-git-strategy should be merged into one skill that covers pipeline and Git strategy best practices. The pipeline best practices should be focused on GitHub Actions.

5. Create a carter-atlassian skill that leverages Jira best practices for managing tickets. Use the external/pm-agent-skills/skills/jira folder as a source of reference. This skill should support operational tasks like adding a comment to a ticket in Jira format, and incorporate best practices for writing tasks, stories, bugs, etc. It should use our Atlassian MCP server.

6. Create a carter-blog skill.

## operations: be deterministic

Multiple times per day I perform operational tasks that are full deterministic and visible for other people.

Git
 - create feature branches, add files, commit them and push to the feature branch

Jira
 - create a comment in a jira ticket regarding the status or progress of the ticket
 - create a jira ticket regarding a bug, a task, story with all the important data the best practices suggests

Regarding both operational tasks, if I'm going to use Carter and be full deterministic I would need to let other that the AI was involved. So:
- In Jira I'd like to have a very brief disclaimer that the comment was made by "carter-bot"
- In Git I'd like to have like a simulated account, like "carter-bot" and I'd like to have verified commits in github (sign the commits with my ssh key).

How can I be as much deterministic as I can in these operational tasks? This must support multiple llms.

There were two suggestions I found in internet:

1.
User Request
    ↓
Intent Extractor (LLM)
    ↓
Typed Plan
    ↓
Approval / Validation
    ↓
Deterministic Executors
    ↓
Verification
    ↓
Structured Result

2.

Orchestator agent
    ↓
intent classifier (LLM)
    ↓
Router + param validator
    ↓
Deterministic zone (executor): functions, commands, etc
    ↓
Verification
    ↓
Structured Result

Review our existing conversation, the plan.md and v2-plan.md files, and the current codebase to have context. Analyse this prompt and think of a solution that better fit this use case. Ask for any clarification.