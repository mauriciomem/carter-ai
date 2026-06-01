
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

## carter-ops deterministic approach refinements.

I don't like the current deterministic approach and the carter-ops calling methodology. It seems too rigid.
Read the docs/interactions folder (skip docs/interactions/prompt folder) and RETHINK EVERYTHING.
Look for best practices on trusted websites.
I left another orchestrator agent file, jennai-maestro.md, as an extra reference if needed.
ANALYZE EVERYTHING DEEPLY AND ASK FOR ANY CLARIFICATIONS IF NEEDED.
The deterministic approach should be:
 - scalable and extensible, without requiring a very long section like "## CRITICAL: Write Operations — carter-ops" in the carter-maestro.md orchestration agent.
 - lightweight, concrete, and functional. Usage of a keyword should be enough.
 - not tied only to "write operations." It should be treated as an operational task when the keyword "ops:" is invoked.
I leave it up to you to decide whether to call carter-ops via the orchestrator, subagent, skill, etc. Use your judgment based on the context and the research you have done. Come up with a plan. This plan should be exclusively for this scope.
REMEMBER: There will be other trivial and operational tasks not tied to carter-ops if the keyword "ops:" is not involved.

## inter platform operation

Review existing code base layout (docs, instructions, knowledge, mcp, ops, skills, agents) and our conversation and explain how memory and knowledge systems work in Carter. How is it used? How it can be triggered? Give a much detail as possible and create a document in docs/ explaining what it is, the memory and knowlege process, and any other data worth mentioned. At any doubt ask.

## operations refinements:

carter installer updates:
1. let the user choose to install mcp servers or not with a CLI optional argument like --mcp. No --mcp flag means no MCP servers.
2. Because the user will be working in diferent projects and in different companies, let the user choose the git bot name for github with a CLI optional argument like --bot-name. If not choosen the default is carter-bot.
3. The git bot name should have a minimal description.

Before implementing this, read the previous conversation, the python code base, and the documentation. Think and update all plan files and documentation to reflect these changes

## multi platform refinements

1. 

On copilot cli:

! Failed to load 7 skills. Run /skills for more details.

● Environment loaded: 1 custom instruction, 47 skills, 1 MCP server, 12 agents, Visual Studio Code connected

● Selected custom agent: carter-maestro

The following skills failed to load:
✖ /Users/mmitolo/CDL/demos/repos/.agents/skills/aws-infra/SKILL.md: missing or malformed YAML frontmatter
✖ /Users/mmitolo/CDL/demos/repos/.agents/skills/demo-ops/SKILL.md: missing or malformed YAML frontmatter
✖ /Users/mmitolo/CDL/demos/repos/.agents/skills/hcp/SKILL.md: missing or malformed YAML frontmatter
✖ /Users/mmitolo/CDL/demos/repos/.agents/skills/python-scripting/SKILL.md: missing or malformed YAML frontmatter
✖ /Users/mmitolo/CDL/demos/repos/.agents/skills/redhat/SKILL.md: missing or malformed YAML frontmatter
✖ /Users/mmitolo/CDL/demos/repos/.agents/skills/terraform/SKILL.md: missing or malformed YAML frontmatter
✖ /Users/mmitolo/CDL/demos/repos/.agents/skills/vault/SKILL.md: missing or malformed YAML frontmatter

2. opencode cli:

> opencode
Configuration is invalid at /Users/mmitolo/.config/opencode/agents/carter-engineer.md
↳ Expected "subagent" | "primary" | "all", got "agent" mode

> opencode                                                     
Configuration is invalid at /Users/mmitolo/.config/opencode/agents/carter-pm.md
↳ Expected "subagent" | "primary" | "all", got "agent" mode


3. I can't see the mauri-bot "Verified" sign in the commit. Instead I have an Unverified tag with the following message: "Upload your public signing SSH key to verify your signature."

This is the log:

> uv run install.py -vv --bot-name mauri-bot
 Carter Installer v1.0
 Target: copilot, opencode
 Bot name: mauri-bot
 MCP servers: no (use --mcp to install)

→ Detecting environment...
  OS: Darwin | Python: 3.13.7 | uv: 0.11.8 (Homebrew 2026-04-27 aarch64-apple-darwin)
...
→ Installing carter-ops...
  ✓ ~/.carter/ops/attribution.py
  ✓ ~/.carter/ops/carter_ops.py
  ✓ ~/.carter/ops/config.py
  ✓ ~/.carter/ops/operations/__init__.py
  ✓ ~/.carter/ops/operations/git_branch.py
  ✓ ~/.carter/ops/operations/git_commit.py
  ✓ ~/.carter/ops/operations/git_flow.py
  ✓ ~/.carter/ops/operations/git_push.py
  ✓ ~/.carter/ops/operations/jira_comment.py
  ✓ ~/.carter/ops/operations/jira_create.py
  ✓ ~/.carter/ops/operations/jira_update.py
  ✓ ~/.carter/ops/output.py
  · ~/.carter/config.toml (exists, not overwriting)
  ✓ ~/.local/bin/carter-ops

...

ai-stuff/ai-assistant git:(main) ✗ 19:14:42
> cat ~/.carter/config.toml 
[attribution]
name = "mauri-bot"
email = "mauri-bot@users.noreply.github.com"
footer = "This comment was generated by mauri-bot."

[git]
signing_key = "/Users/mmitolo/.ssh/id_rsa_hashicorp"

[jira]
url = ""
email = ""
# token comes from JIRA_TOKEN or ATLASSIAN_API_TOKEN env var — never in config file
ai-stuff/ai-assistant git:(main) ✗ 19:14:53

> git config list --global
ai-stuff/ai-assistant git:(main) ✗ 19:15:11

user.email=mauricio.estebanmitolo@hashicorp.com
user.name=Mauricio Mitolo
user.signingkey=/Users/mmitolo/.ssh/id_rsa_hashicorp
credential.https://github.com.helper=
credential.https://github.com.helper=!/opt/homebrew/bin/gh auth git-credential
credential.https://gist.github.com.helper=
credential.https://gist.github.com.helper=!/opt/homebrew/bin/gh auth git-credential
gpg.format=ssh
commit.gpgsign=true




## 

You as carter-maestro, personal assistant, you need to improve yourself constantly. As a result, do a VERY DEEP analysis of another ai-assistant called yui, in the folder yui-soul. DO A VERY DETAILED ASSESMENT OF THIS AI ASSISTANT. REVIEW EVERYTING, EVERY CORNER, EDGE CASE, EVERY MINOR DETAIL to deeply understand how it works, how its structured, how the content and intent is layed out, and every important aspect of this ai-assistant. This should result in a very detailed documentation. Remember, you need to improve yourself by extracting the best properties, features, characteristic and anything that is worth leaning from this. The documentation then will be used to trigger other documents, such as implementation plans.


### 

Now, do a final pass. Repeat the extremelly detailed assessment of yui ai assisstant, now without taking into account any session record or conversation history. Read and review in detail the yui-soul-assessment.md, the implementation-plan.md. Question everything again, look for stronger points and impact. Consider what I consider the features I prefer:
 - iteration with quality gates
 - file system in memory
 - template driven, configurable agent generation. Leverage jinja2 instead.
 - umbrella workpace. Make it an optional argument to pass optinally to a project
 - TDD development focused
 - redaction system
In terms of personality I'd like: a bit more sceptical, reviewer, question focused assisstance.
As a result, overwrite and update the yui-soul-assessment.md and, if worth prepare question to update the implementation-plan.md


I'd like:
 - reviewer focused, quiestion focused