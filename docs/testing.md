# Testing Guide

This document covers the Carter test suite — what it tests, how to run it, how it works, and how to extend it when adding new features.

## Overview

The test suite validates three systems:

| System | Test File | What It Covers |
|--------|-----------|----------------|
| **Installer** | `tests/test_install.py` | File copying, MCP merging, manifest tracking, idempotency |
| **Scaffold (CLI + Templates)** | `tests/test_scaffold.py` | Config loading, template rendering, quality gates, workspace init |
| **Carter-Ops** | `tests/ops/test_operations.py` | CLI parsing, operations, attribution, output formatting |

The tests run in full isolation using temporary directories — they never touch your real `~/.copilot/`, `~/.config/opencode/`, or any workspace paths.

## Prerequisites

All three suites import from the installed `carter` package (Click, Jinja2,
PyYAML, httpx), so the simplest setup is a venv with the package installed in
editable mode:

```bash
# Create and activate a venv with the package installed
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Run everything

```bash
# From the venv (covers all three test files — 211 tests)
python -m pytest tests/ -v
```

### Run a single suite

```bash
python -m pytest tests/test_install.py -v     # installer (65)
python -m pytest tests/test_scaffold.py -v    # scaffold (67)
python -m pytest tests/test_parity.py -v      # agent source parity (8)
python -m pytest tests/ops/ -v                # carter-ops (71)
```

## Continuous Integration

Every push to `main` and every pull request runs the suite via GitHub Actions
([.github/workflows/ci.yml](../.github/workflows/ci.yml)) on Python 3.11 and 3.13:

```bash
uv venv --clear
uv pip install -e ".[dev]"
python -m pytest tests/ -q                                  # 211 unit tests
python -m pytest evals/test_skills.py evals/test_routing.py -q  # 28 offline evals
```

The live evals (`evals/test_live.py`, marked `live`) require an API key and are
**not** run in CI. The agent-generation drift check described in
[ADR-0002](adr/0002-single-source-agent-generation.md) is deferred until the
static/template sources are reconciled; until then, `tests/test_parity.py` is the
drift guardrail.

## Tools & Libraries

| Tool | Purpose |
|------|---------|
| [pytest](https://docs.pytest.org/) | Test runner and assertion library |
| `tmp_path` (pytest built-in) | Provides a unique temporary directory per test, cleaned up automatically |
| `pathlib.Path` | All file operations use `Path` objects (no `os.path`) |
| `json` (stdlib) | Used to create and verify JSON settings files |
| [Jinja2](https://jinja.palletsprojects.com/) | Template engine (scaffold tests exercise template rendering) |
| [PyYAML](https://pyyaml.org/) | YAML config parsing (scaffold tests exercise config loading) |

No external mocking libraries are used. Both the installer and the scaffold accept path parameters that redirect file operations to temp directories.

## Project Layout

```
tests/
├── conftest.py             # Shared fixtures (base_dir, settings, etc.)
├── test_install.py         # Installer tests (65 tests, 21 classes)
├── test_scaffold.py        # Scaffold tests (67 tests, 9 classes)
├── test_parity.py          # Agent source-parity tests (8 tests, 3 classes)
└── ops/
    ├── conftest.py         # Ops path setup
    └── test_operations.py  # Carter-ops tests (71 tests, 27 classes)
```

The full suite is **211 tests** (`python -m pytest tests/ -v`).

## Fixtures (conftest.py)

Fixtures are reusable setup functions that pytest injects into tests by name. All fixtures live in `tests/conftest.py`.

| Fixture | Type | Description |
|---------|------|-------------|
| `repo_root` | `Path` | Absolute path to the Carter repository root. Used when tests need to reference source files. |
| `base_dir` | `Path` | A fresh `tmp_path` directory. Every installer function accepts this as a parameter, so all file writes go here instead of real user directories. |
| `copilot_dir` | `Path` | `base_dir/copilot/`, pre-created. Represents `~/.copilot/`. |
| `opencode_dir` | `Path` | `base_dir/opencode/`, pre-created. Represents `~/.config/opencode/`. |
| `vscode_settings` | `Path` | An empty `settings.json` at `base_dir/vscode/settings.json`. Simulates a fresh VS Code config. |
| `existing_settings` | `Path` | A `settings.json` pre-populated with `editor.fontSize` and a non-Carter MCP server. Simulates a user who already has VS Code configured. |

### How `base_dir` Isolation Works

The installer's functions (e.g., `install_agents`, `install_skills`) accept a `base_dir` argument. In production, this defaults to the user's home directory. In tests, it's always `tmp_path` — a unique temporary directory that pytest creates and cleans up per test. This means:

- Tests never read or write to `~/.copilot/`
- Every test starts with a clean filesystem
- Tests can run in parallel without conflicts

## Test Classes

The following sections document each test class across all three test files, grouped by system.

---

## Scaffold Tests (`tests/test_scaffold.py`)

These tests validate the `carter` CLI package — config loading, Jinja2 template rendering, quality gate logic, and workspace initialization. They use `tmp_path` for all filesystem operations.

### TestConfig (6 tests)

Validates `carter.yaml` loading, defaults, and error handling.

| Test | What It Verifies |
|------|------------------|
| `test_generate_default_config` | Default config includes all required sections (workspace, identity, personality, agents, quality_gate, redaction, tdd, state, target) |
| `test_load_config_from_file` | A valid `carter.yaml` is parsed and returned as a dict |
| `test_load_config_missing_file` | Missing config file raises `ConfigError` |
| `test_load_config_invalid_yaml` | Malformed YAML raises `ConfigError` |
| `test_write_config` | `write_config()` produces a valid YAML file at the target path |
| `test_config_merges_with_defaults` | User-provided partial config merges with defaults (no missing keys) |

### TestConfigIsolation (4 tests)

Validates that `generate_default_config()` returns deep copies — mutating one config never corrupts the shared defaults.

| Test | What It Verifies |
|------|------------------|
| `test_mutating_agents_list_does_not_corrupt_defaults` | Mutating a generated config's `agents` list leaves `DEFAULT_CONFIG` intact |
| `test_mutating_nested_dict_does_not_corrupt_defaults` | Mutating a nested dict doesn't leak into defaults |
| `test_mutating_redaction_categories_does_not_corrupt_defaults` | Mutating `redaction.categories` doesn't leak into defaults |
| `test_two_generated_configs_are_independent` | Two generated configs share no mutable state |

### TestConfigMerge (7 tests)

Validates the merge-with-defaults semantics (partial configs, list replacement, key preservation).

| Test | What It Verifies |
|------|------------------|
| `test_partial_config_gets_defaults_for_missing_sections` | Missing sections are filled from defaults |
| `test_partial_nested_dict_gets_missing_keys` | Nested dicts get missing keys merged in |
| `test_user_list_values_not_merged_with_defaults` | Lists use replace semantics (user's list wins) |
| `test_user_explicit_none_preserved` | An explicit `None` from the user is preserved |
| `test_extra_user_keys_preserved` | Unknown user keys survive the merge |
| `test_full_config_roundtrip_unchanged` | A complete config round-trips unchanged |
| `test_merged_config_renders_templates_successfully` | A merged config renders all templates without error |

### TestAgentValidation (6 tests)

Validates that the `agents` list is sanitized — only known agent names render, blocking path traversal and injection.

| Test | What It Verifies |
|------|------------------|
| `test_unknown_agent_raises_config_error` | An unknown agent name raises `ConfigError` |
| `test_error_message_lists_valid_agents` | The error message lists the valid agent names |
| `test_path_traversal_rejected` | Path-traversal values (e.g., `../`) are rejected |
| `test_empty_string_rejected` | Empty agent names are rejected |
| `test_special_characters_rejected` | Names with special characters are rejected |
| `test_valid_agents_pass_validation` | All known agent names pass validation |

### TestScaffold (11 tests)

Validates Jinja2 template rendering — that all agents, instructions, and quality gate content render correctly from config values.

| Test | What It Verifies |
|------|------------------|
| `test_render_agents_creates_all_files` | Every configured agent `.md` file is rendered to the output directory (7 by default, including `carter-narrator.md`) |
| `test_rendered_agent_contains_identity` | Agent files include the configured identity name and role |
| `test_rendered_agent_contains_boundaries` | Agent files define clear operational boundaries |
| `test_render_instructions` | `copilot-instructions.md` is rendered with global rules |
| `test_instructions_contain_agents_list` | Instructions file lists all available agents |
| `test_instructions_contain_quality_gate` | Instructions file references quality gate requirements |
| `test_maestro_has_routing_table` | Maestro agent has the domain-to-agent routing table |
| `test_engineer_has_tdd_workflow` | Engineer agent includes TDD workflow section |
| `test_engineer_strict_tdd` | With `tdd.strict: true`, engineer requires tests before code |
| `test_engineer_relaxed_tdd` | With `tdd.strict: false`, engineer suggests but doesn't require tests first |
| `test_custom_personality` | Config personality values (tone, skepticism) appear in rendered output |

### TestQualityGate (8 tests)

Validates that quality gate configuration translates correctly into rendered agent behavior.

| Test | What It Verifies |
|------|------------------|
| `test_must_haves_in_maestro` | Maestro agent validates all configured must_haves before completing |
| `test_must_haves_in_engineer` | Engineer agent validates must_haves (tests passing, no lint errors) |
| `test_output_format_structured` | Quality gate specifies structured output format |
| `test_iteration_tracking` | Rendered agents include iteration tracking (attempt counting) |
| `test_quality_gate_disabled` | With quality gate disabled, no validation blocks appear |
| `test_reviewer_checklist_architect` | Architect has security and scalability review checklist |
| `test_reviewer_checklist_engineer` | Engineer has code quality and test coverage checklist |
| `test_scaled_skepticism` | Skepticism level from config controls review rigor |

### TestState (8 tests)

Validates workspace initialization — the `.carter/` directory structure, knowledge files, git setup, and gitignore behavior.

| Test | What It Verifies |
|------|------------------|
| `test_init_creates_carter_dir` | `init_workspace()` creates `.carter/` with proper subdirectory structure |
| `test_init_creates_knowledge_files` | All 5 knowledge files are created (lessons-learned, gotchas, tools, decisions, patterns) |
| `test_knowledge_files_not_overwritten` | Existing knowledge content is preserved on re-init |
| `test_init_creates_git_repo` | `.carter/.git/` is initialized by default |
| `test_init_no_git_flag` | `--no-git-state` skips git initialization |
| `test_gitignore_single_repo_mode` | In single-repo mode, `.carter/` is added to `.gitignore` |
| `test_gitignore_not_modified_if_present` | If `.carter/` is already in `.gitignore`, no duplicate entry added |
| `test_init_idempotent` | Running init twice doesn't error or duplicate files |

### TestNarrator (11 tests)

Validates the `carter-narrator` redaction agent template and the `redaction` config block.

| Test | What It Verifies |
|------|------------------|
| `test_narrator_renders` | `carter-narrator.md` renders when `narrator` is in the agents list |
| `test_narrator_has_identity` | Narrator file includes its identity |
| `test_narrator_has_role` | Narrator file includes its role |
| `test_narrator_has_boundaries` | Narrator file defines operational boundaries |
| `test_redaction_rules_present_when_enabled` | Redaction rules appear when `redaction.enabled: true` |
| `test_redaction_rules_absent_when_disabled` | Redaction rules disappear when disabled |
| `test_all_categories_render` | All configured redaction categories render |
| `test_subset_categories_render` | A subset of categories renders correctly |
| `test_anti_bypass_clause_present` | The anti-bypass clause is present in the rendered agent |
| `test_narrator_absent_when_not_in_agents` | Narrator is not rendered when removed from the agents list |
| `test_maestro_routes_to_narrator` | Maestro's routing references the narrator agent |

### TestRenderDiscovery (6 tests)

Validates that `carter init`/`update` write agents and instructions to the paths
each tool actually discovers (ADR-0002), honoring `config["target"]`.

| Test | What It Verifies |
|------|------------------|
| `test_copilot_target_writes_github_paths` | `target: copilot` writes `.github/agents/*.md` + `.github/copilot-instructions.md` (and not the legacy `agents/`) |
| `test_opencode_target_writes_opencode_paths` | `target: opencode` writes `.opencode/agents/*.md` + `AGENTS.md` |
| `test_all_target_writes_both` | `target: all` writes both target trees |
| `test_instructions_skip_if_exists` | A pre-existing instruction file is preserved; agents still written |
| `test_agents_rewritten_on_update` | Carter-owned `carter-*` agents are overwritten so `carter update` refreshes them |
| `test_resolve_targets` | `_resolve_targets` expands `all` to both; passes others through |

---

## Installer Tests (`tests/test_install.py`)

### TestInstallAgents (4 tests)

Validates that agent Markdown files are correctly copied to target directories.

| Test | What It Verifies |
|------|-----------------|
| `test_creates_copilot_agents` | All 7 `carter-*.md` files (incl. `carter-narrator.md`) are created under `base_dir/copilot/agents/` |
| `test_creates_opencode_agents` | Same 7 files under `base_dir/opencode/agents/` |
| `test_creates_both_targets` | Both targets installed simultaneously produce 7 files each |
| `test_manifest_tracks_files` | Every installed file is recorded in the manifest with a `sha256:` hash |

### TestInstallSkills (2 tests)

Validates that skill directories and their `SKILL.md` files are created.

| Test | What It Verifies |
|------|-----------------|
| `test_creates_copilot_skills` | All 22 `carter-*` skill directories are created, each with a `SKILL.md`, plus sub-files for terraform/packer |
| `test_creates_opencode_skills` | Same 22 directories under the OpenCode target |

### TestInstallInstructions (1 test)

| Test | What It Verifies |
|------|-----------------|
| `test_creates_instructions` | `copilot-instructions.md` is created and contains "Carter" |

### TestInstallKnowledge (2 tests)

Validates the knowledge base template installation.

| Test | What It Verifies |
|------|-----------------|
| `test_creates_knowledge_files` | All 6 knowledge templates are created (decisions, mistakes, patterns, debugging, infrastructure, project-history) |
| `test_does_not_overwrite_existing` | If a user has edited a knowledge file, the installer preserves their content instead of overwriting |

### TestIdempotency (2 tests)

Validates that running the installer multiple times is safe.

| Test | What It Verifies |
|------|-----------------|
| `test_second_run_unchanged` | A second install reports all 7 agent files as `unchanged` (0 created, 0 updated) |
| `test_modified_file_detected_as_updated` | If a file is modified externally, the installer detects and reports it as `updated` |

### TestMCPMerging (8 tests)

Validates JSON merging logic for VS Code `settings.json`, including JSONC edge cases.

| Test | What It Verifies |
|------|------------------|
| `test_merge_into_empty_settings` | Carter MCP servers are added to an empty `settings.json` |
| `test_preserves_existing_servers` | Existing non-Carter MCP servers survive the merge |
| `test_preserves_other_settings` | Non-MCP settings (e.g., `editor.fontSize`) are untouched |
| `test_handles_jsonc_with_comments` | Single-line and block comments don't break parsing |
| `test_handles_jsonc_with_trailing_commas` | VS Code's trailing commas are handled |
| `test_handles_jsonc_comments_inside_strings` | Comments inside string values are preserved |
| `test_unparseable_file_not_overwritten` | Truly broken files are left untouched |
| `test_backup_created_before_modify` | Settings file is backed up before modification |

### TestManifest (2 tests)

Validates the manifest file (`.carter-manifest.json`) used for tracking and uninstall.

| Test | What It Verifies |
|------|-----------------|
| `test_write_and_read_manifest` | Manifest round-trips correctly (write → read → identical data) |
| `test_read_nonexistent_manifest` | Reading a missing manifest returns `None` instead of crashing |

### TestUninstall (2 tests)

Validates clean removal of Carter files.

| Test | What It Verifies |
|------|-----------------|
| `test_uninstall_removes_carter_files` | All `carter-*` agent and skill files are removed |
| `test_uninstall_preserves_non_carter_files` | Non-Carter files in the same directories are not deleted |

### TestHashing (2 tests)

Validates the SHA-256 hashing utility used for change detection.

| Test | What It Verifies |
|------|-----------------|
| `test_sha256_consistent` | Same file produces the same hash on repeated calls; hash starts with `sha256:` |
| `test_sha256_different_content` | Different content produces different hashes |
### TestInstallOps (4 tests)

Validates carter-ops setup. The executor ships inside the installed `carter`
package, so the installer only generates `~/.carter/config.toml` — it copies no
source files and creates no wrapper script.

| Test | What It Verifies |
|------|------------------|
| `test_generates_config_toml` | `config.toml` is generated with `[attribution]`, `[git]`, and `[jira]` sections |
| `test_does_not_overwrite_existing_config` | Custom `config.toml` content is preserved on re-install |
| `test_manifest_tracks_config` | The generated `config.toml` is tracked in the manifest |
| `test_idempotent` | Second install reports `unchanged` with 0 `created` |
### TestBotName (3 tests)

Validates the `--bot-name` CLI flag for custom git attribution.

| Test | What It Verifies |
|------|-------------------|
| `test_default_bot_name` | Default config uses `carter-bot` name and derived email |
| `test_custom_bot_name` | `--bot-name "acme-bot"` produces `acme-bot` name and `acme-bot@users.noreply.github.com` email |
| `test_custom_bot_name_footer` | Footer text uses the custom bot name |

### TestMCPFlag (2 tests)

Validates the `--mcp` flag for opt-in MCP server installation.

| Test | What It Verifies |
|------|-------------------|
| `test_no_mcp_flag_skips_servers` | Without `--mcp`, no MCP server entries are written to settings files |
| `test_mcp_flag_installs_servers` | With `--mcp`, MCP server entries are written to VS Code settings |

### TestCarterOpsSkill (2 tests)

Validates that the carter-ops skill is installed alongside other skills.

| Test | What It Verifies |
|------|-------------------|
| `test_carter_ops_skill_installed` | `carter-ops/SKILL.md` exists under copilot skills and contains `ops:`, `carter-ops`, and `dry-run` |
| `test_carter_ops_skill_opencode` | `carter-ops/SKILL.md` exists under OpenCode skills |

### TestOpenCodeRules (3 tests)

Validates OpenCode global rules file generation.

| Test | What It Verifies |
|------|-------------------|
| `test_creates_agents_md` | `AGENTS.md` is created under OpenCode root with `ops:` and `carter-ops` references |
| `test_skipped_for_copilot_only` | `AGENTS.md` is not created when target is copilot only |
| `test_does_not_overwrite` | Existing `AGENTS.md` content is preserved |

### TestOpsOneLiner (3 tests)

Validates the ops enforcement one-liner across agents and skills.

| Test | What It Verifies |
|------|-------------------|
| `test_agents_have_ops_oneliner` | All 7 installed agent files contain `ops:` and `carter-ops` references |
| `test_no_critical_section_in_agents` | No agent file contains the old `CRITICAL: Write Operations` section |
| `test_no_deterministic_ops_in_skills` | Pipeline and atlassian skills have no `<deterministic-operations>` blocks |

### TestNarratorAgent (3 tests)

Validates ADR-0001: the narrator is a first-class, always-installed agent.

| Test | What It Verifies |
|------|-------------------|
| `test_narrator_installed` | `carter-narrator.md` is installed by `install_agents` (system-level, not scaffold-only) |
| `test_narrator_has_all_redaction_categories` | The static source bakes in redaction ON with all 7 categories + the anti-bypass clause |
| `test_narrator_references_content_skills` | The agent references `carter-docs` and `carter-story` |

### TestContentSkills (3 tests)

Validates ADR-0001: the `carter-docs` and `carter-story` skills and their anti-drift contracts.

| Test | What It Verifies |
|------|-------------------|
| `test_content_skills_installed` | `carter-docs/SKILL.md` and `carter-story/SKILL.md` are installed |
| `test_docs_skill_delegates` | `carter-docs` delegates to `carter-adr`/`carter-diagram`/`pptx` and cites Diátaxis + Keep a Changelog + Conventional Commits |
| `test_brief_register_single_source` | The Brief register is defined once in `carter-docs`; `carter-atlassian`/`carter-ops` only reference it |

### TestInstallMemories (3 tests)

Validates that `carter install` creates the visible memory directory structure under `~/.carter/memories/`.

| Test | What It Verifies |
|------|-------------------|
| `test_creates_memory_directories` | `user/`, `session/`, and `repo/` scopes are created under `~/.carter/memories/` |
| `test_idempotent` | Re-running leaves existing memory directories untouched |
| `test_manifest_tracks_directories` | The memory directories are recorded in the manifest |

### TestCarterReflectSkill (2 tests)

Validates that the `carter-reflect` skill is installed alongside the other skills.

| Test | What It Verifies |
|------|-------------------|
| `test_reflect_skill_installed` | `carter-reflect/SKILL.md` exists under the copilot skills directory |
| `test_reflect_skill_opencode` | `carter-reflect/SKILL.md` exists under the OpenCode skills directory |

### TestVisibleMemoryReferences (3 tests)

Validates that installed instructions and rules reference the visible memory system and reflect skill.

| Test | What It Verifies |
|------|-------------------|
| `test_instructions_reference_visible_memory` | `copilot-instructions.md` references `~/.carter/memories/` |
| `test_opencode_rules_reference_visible_memory` | OpenCode `AGENTS.md` references visible memory scopes |
| `test_maestro_has_reflect_skill` | The maestro agent references the `carter-reflect` skill |

### TestJSONCParsing (8 tests)

Validates the JSONC (JSON-with-comments) parser used to read VS Code `settings.json` safely.

| Test | What It Verifies |
|------|-------------------|
| `test_strip_single_line_comments` | `//` line comments are stripped before parsing |
| `test_strip_block_comments` | `/* ... */` block comments are stripped |
| `test_strip_trailing_commas` | Trailing commas (legal in JSONC) are handled |
| `test_preserves_comments_inside_strings` | `//`-like sequences inside string values are preserved |
| `test_preserves_slashes_inside_strings` | Slashes inside strings (e.g., URLs) are preserved |
| `test_load_jsonc_returns_none_on_garbage` | Unparseable content returns `None` (never corrupts the file) |
| `test_load_jsonc_returns_none_on_missing_file` | A missing file returns `None` |
| `test_realistic_vscode_settings` | A realistic VS Code `settings.json` round-trips correctly |

---

## Carter-Ops Tests (`tests/ops/test_operations.py`)

The ops test file validates the carter-ops CLI and all 11 operations. Imports
come from the installed `carter.ops` package.

### TestConfig (4 tests)

| Test | What It Verifies |
|------|------------------|
| `test_load_defaults` | Default config has `carter-bot` name and email |
| `test_load_from_toml` | Config values are loaded from a TOML file |
| `test_env_vars_override` | `ATLASSIAN_URL`, `ATLASSIAN_EMAIL`, `JIRA_TOKEN` override file values |
| `test_validate_jira_missing` | Missing Jira credentials produce 3 validation errors |

### TestAttribution (4 tests)

| Test | What It Verifies |
|------|------------------|
| `test_git_author` | Author string matches `carter-bot <email>` format |
| `test_append_jira_footer` | Footer is appended to comment body |
| `test_attribution_summary_git` | Git summary includes bot name |
| `test_attribution_summary_jira` | Jira summary includes bot name |

### TestOutput (4 tests)

| Test | What It Verifies |
|------|------------------|
| `test_dry_run_output` | Dry-run output has correct phase, operation, steps |
| `test_execute_output` | Execute output has success flag |
| `test_error_output` | Error output includes code, message, suggestion |
| `test_error_output_no_suggestion` | Suggestion field is omitted when empty |

### TestOperationRegistry (3 tests)

| Test | What It Verifies |
|------|------------------|
| `test_discover_operations` | All 11 operations are discovered and registered |
| `test_get_operation` | Looking up by name returns the correct instance |
| `test_get_unknown_operation` | Unknown name returns `None` |

### Operation Dry-Run Tests (6 classes, 12 tests)

Every operation's `dry_run()` method is tested directly — these are always safe (no side effects).

| Class | Tests | What It Verifies |
|-------|-------|------------------|
| `TestGitBranchDryRun` | 3 | Plan steps, validation (missing name, invalid format) |
| `TestGitCommitDryRun` | 2 | Commit plan includes author, validation (missing message) |
| `TestGitPushDryRun` | 1 | Push plan includes branch |
| `TestGitFlowDryRun` | 2 | Composite plan has 6 steps and 3 side effects, validation |
| `TestJiraCommentDryRun` | 3 | Plan includes ticket key, validation (missing ticket, bad format) |
| `TestJiraCreateDryRun` | 2 | Plan includes project/type, validation (missing project) |
| `TestJiraUpdateDryRun` | 2 | Composite plan has 2 side effects, validation (no action) |

### CLI Parsing Tests (10 tests)

| Test | What It Verifies |
|------|------------------|
| `test_parse_list` | `--list` is recognized |
| `test_parse_dry_run` | Operation, params, and phase are parsed correctly |
| `test_parse_execute` | `--execute` phase with comma-separated files |
| `test_parse_empty` | Empty args return empty operation |
| `test_list_operations` | `main(["--list"])` outputs all operations as JSON |
| `test_no_operation_shows_error` | Missing operation exits with code 1 |
| `test_no_phase_shows_error` | Missing `--dry-run`/`--execute` exits with code 1 |
| `test_unknown_operation` | Unknown operation exits with code 1 |
| `test_validation_error` | Missing required params exits with code 1 + JSON error |
| `test_dry_run_success` | Valid dry-run exits with code 0 + JSON plan |

### Execute Tests (3 classes, 5 tests)

Execution tests use `unittest.mock.patch` to mock `subprocess.run`, verifying the operations call git correctly without actually running commands.

| Class | Tests | What It Verifies |
|-------|-------|------------------|
| `TestGitBranchExecute` | 2 | Success (3 subprocess calls), failure on CalledProcessError |
| `TestGitCommitExecute` | 1 | Success with commit SHA extraction |
| `TestGitPushExecute` | 2 | Success, rejection produces suggestion field |

### GitHub Operations (8 classes, 16 tests)

The GitHub operations use `httpx` against the REST API. Dry-run tests verify the
plan and validation; execute tests mock the HTTP client.

| Class | Tests | What It Verifies |
|-------|-------|------------------|
| `TestGitHubConfig` | 2 | `GITHUB_TOKEN` is loaded; `validate_github()` flags a missing token |
| `TestGitHubAttribution` | 2 | The Markdown footer is appended to issue/PR bodies |
| `TestGhIssueDryRun` | 4 | Plan includes repo/title/labels; validation (missing repo, missing title) |
| `TestGhIssueExecute` | 2 | Success returns issue URL/number; API error surfaces a suggestion |
| `TestGhIssueCommentDryRun` | 2 | Plan includes repo/issue; validation |
| `TestGhIssueCommentExecute` | 1 | Success posts a comment with footer |
| `TestGhPrDryRun` | 2 | Plan includes head/base; validation |
| `TestGhPrExecute` | 2 | Success returns PR URL; draft flag honored |
| `TestGhPrCommentDryRun` | 2 | Plan includes repo/pr; validation |
| `TestGhPrCommentExecute` | 1 | Success posts a PR comment with footer |

### Subcommand Tests (2 classes, 6 tests)

Validate the utility subcommands the model calls directly.

| Class | Tests | What It Verifies |
|-------|-------|------------------|
| `TestAuditSubcommand` | 4 | `carter ops audit` appends a JSONL entry; requires `--operation` and `--result`; parses `--params`/`--identifiers` JSON |
| `TestConfigSubcommand` | 2 | `carter ops config --emit` prints config values as JSON; rejects bad usage |

---

## Parity Tests (`tests/test_parity.py`)

Carter defines each agent twice — a static `agents/carter-*.md` (copied by
`carter install`) and a `templates/agents/carter-*.md.j2` (rendered by
`carter init`/`update`). The two are hand-maintained, so these tests lock the
*invariants* that must never drift rather than asserting body byte-equality. Both
sources now emit identical YAML frontmatter (ADR-0002 follow-up). This is the
phase-1 guardrail from [ADR-0002](adr/0002-single-source-agent-generation.md).

### TestAgentSourceParity (3 tests)

| Test | What It Verifies |
|------|------------------|
| `test_static_and_template_agent_sets_match` | The set of agents in `agents/` equals the set in `templates/agents/` (guards the ADR-0001 drift where the narrator had a template but no static file) |
| `test_static_agents_have_frontmatter` | Every static agent carries `---` frontmatter with `description:` and `mode:` |
| `test_static_agents_have_ops_oneliner` | Every static agent contains the `ops:` / `carter-ops` one-liner |

### TestNarratorParity (2 tests)

| Test | What It Verifies |
|------|------------------|
| `test_redaction_invariants_in_both_sources` | Both narrator sources contain `NON-NEGOTIABLE`, the Anti-Bypass clause, and all 7 redaction categories |
| `test_reader_principle_in_both_sources` | Both narrator sources contain the "write for the reader" principle |

### TestRenderedFrontmatterParity (3 tests)

| Test | What It Verifies |
|------|------------------|
| `test_rendered_agents_have_valid_frontmatter` | Every rendered agent begins with valid YAML frontmatter carrying `description`, `mode`, and a numeric `temperature` |
| `test_rendered_frontmatter_matches_static` | Each rendered agent's frontmatter equals its static `agents/*.md` counterpart (the ADR-0002 scaffold-bug fix) |
| `test_mode_vocabulary_is_valid_and_orchestrator_only` | Pure-orchestrator model: maestro is the sole `primary`, all others `subagent`, all valid OpenCode modes |

## Extending the Test Suite

### When to Add Tests

Add tests when you:

- Add a new installer function (e.g., `install_themes()`)
- Add a new file type that gets installed (e.g., a new agent or skill)
- Change merge logic (e.g., adding OpenCode MCP support)
- Modify manifest structure
- Add new CLI flags

### How to Add a Test

**1. Decide which class it belongs to.** Group by feature. If none fit, create a new class with a section comment:

```python
# ──────────────────────────────────────────────────────────────────────────────
# Your Feature Name
# ──────────────────────────────────────────────────────────────────────────────

class TestYourFeature:
    ...
```

**2. Use `base_dir` for filesystem isolation.** Every test that touches files should use the `base_dir` fixture:

```python
def test_my_new_feature(self, base_dir: Path) -> None:
    manifest = {"files": [], "file_hashes": {}}
    backup = base_dir / "backup"

    # Call the installer function with base_dir
    install.my_new_function(["copilot"], base_dir, manifest, backup)

    # Assert the expected outcome
    output = base_dir / "copilot" / "my_feature" / "output.md"
    assert output.exists()
    assert "expected content" in output.read_text()
```

**3. For JSON/settings tests**, create the settings file in the test body or use the `vscode_settings` / `existing_settings` fixtures:

```python
def test_my_merge_logic(self, base_dir: Path) -> None:
    settings = base_dir / "vscode" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"existing.key": "value"}))

    install.my_merge_function(settings, new_data)

    result = json.loads(settings.read_text())
    assert result["existing.key"] == "value"  # preserved
    assert "new.key" in result                  # added
```

**4. Test idempotency for any new install function.** Run it twice and verify the second run reports no changes:

```python
def test_idempotent(self, base_dir: Path) -> None:
    manifest = {"files": [], "file_hashes": {}}
    backup = base_dir / "backup"

    install.my_function(["copilot"], base_dir, manifest, backup)

    manifest2 = {"files": [], "file_hashes": {}}
    stats = install.my_function(["copilot"], base_dir, manifest2, backup)

    assert stats["unchanged"] > 0
    assert stats["created"] == 0
```

**5. Test uninstall for any new file type.** Verify Carter files are removed and non-Carter files survive.

### Adding a New Fixture

If multiple tests need the same setup, add a fixture to `conftest.py`:

```python
@pytest.fixture
def my_fixture(base_dir: Path) -> Path:
    """Describe what this sets up."""
    d = base_dir / "some" / "path"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

Fixtures can depend on other fixtures (like `base_dir` above). Pytest resolves the dependency graph automatically.

## Common Patterns

### Verifying file counts

```python
actual = sorted(f.name for f in some_dir.glob("carter-*.md"))
assert len(actual) == 6
```

### Verifying file content

```python
content = some_file.read_text()
assert "expected string" in content
```

### Verifying non-destructive behavior

```python
# Pre-create a file with custom content
existing.write_text("custom content\n")

# Run installer
install.some_function(...)

# Verify it wasn't overwritten
assert existing.read_text() == "custom content\n"
```

### Verifying JSON merging

```python
data = json.loads(settings.read_text())
assert "new-key" in data["mcp.servers"]     # added
assert "old-key" in data["mcp.servers"]     # preserved
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'install'`

The test file adds the repo root to `sys.path` at import time. Make sure you're running pytest from the repository root:

```bash
cd ~/carter-ai
uv run --with pytest pytest tests/ -v
```

### Tests pass locally but fail in CI

Check that the CI runner has `uv` and Python 3.11+ installed. See the GitHub Actions workflow in `.github/workflows/` if available.

### A test is failing after adding a new agent/skill

If you added a new file (e.g., a 7th agent), update the expected counts in the relevant test assertions. Search for the current count (e.g., `== 6`) and update it.

### Ops tests fail with `ModuleNotFoundError`

The ops tests manipulate `sys.path` to import from `ops/`. Make sure you're running from the repo root and that `tests/ops/conftest.py` exists (it adds the path).
