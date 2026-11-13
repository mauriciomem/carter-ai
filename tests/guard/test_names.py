# ruff: noqa: E501
"""The names Carter writes to the user's machine, pinned.

A rename here is a deliberate act: it changes what is written to the user's machine
(OpenCode config statements, ``guard-state.json``). Change a snapshot only on purpose.
"""

from __future__ import annotations

from carter.guard import state
from carter.identity import policyset
from carter.identity.rules import load_rules

# The seven consent groups.
GROUPS = ("g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit", "alias", "repo_hooks")

# statement ids per group. gh allows are generated from the allowlist.
IDS_BY_GROUP = {
    "g2": ["deny-git-push", "deny-git-send-pack", "deny-gh"],
    "sudo-docker": ["deny-sudo", "deny-docker"],
    "read-edit-denies": [
        "deny-read-ssh",
        "deny-read-gh-config",
        "deny-read-opencode-service",
        "deny-read-git-credentials",
        "deny-read-carter-secrets",
        "deny-edit-ssh",
    ],
    "config-edit": [
        "deny-edit-opencode-global",
        "deny-edit-opencode-project-json",
        "deny-edit-opencode-project-jsonc",
        "deny-edit-opencode-dir",
        "deny-edit-git-hooks",
        "deny-edit-git-config",
        "deny-edit-gitconfig",
        "deny-edit-git-xdg",
        "deny-edit-carter-config",
        "deny-edit-carter-bin",
        "deny-edit-carter-hooks",
        "deny-edit-carter-run",
        "deny-edit-carter-secrets",
        "deny-edit-carter-audit",
        "deny-edit-carter-backups",
        "deny-edit-carter-manifest",
        "deny-edit-carter-workspaces",
        "deny-edit-carter-isolation",
        "deny-edit-carter-gitconfig",
        "deny-edit-carter-guard-state",
        "deny-edit-plugin",
    ],
}

# The gh allowlist; `gh status` is left out (it 403s with a fine-grained token).
GH_ALLOW_VERBS = (
    "pr view",
    "pr list",
    "pr diff",
    "pr checks",
    "pr create",  # PRs are allowed (opened, edited, commented by agents; merged by the human)
    "pr edit",
    "pr comment",
    "issue view",
    "issue list",
    "run view",
    "run list",
    "repo view",
    "search",
)

AGENT_PERMISSION_DENIES = ("carter_push",)  # removed carter_pr


def test_consent_groups_are_the_seven_c61_names() -> None:
    assert tuple(g.id for g in policyset.consent_groups()) == GROUPS


def test_only_alias_is_optional() -> None:
    groups = policyset.consent_groups()
    assert [g.id for g in groups if g.optional] == ["alias"]
    assert {g.id: g.rev for g in groups} == CONSENT_REVS


def test_every_group_has_a_one_line_effect() -> None:
    for group in policyset.consent_groups():
        assert group.effect and "\n" not in group.effect, group.id


def test_statement_ids_per_group_in_order() -> None:
    by_group: dict[str, list[str]] = {}
    for st in policyset.policy_set():
        by_group.setdefault(st.group, []).append(st.id)
    assert by_group == IDS_BY_GROUP


def test_statement_ids_are_unique_and_kebab_case() -> None:
    ids = [s.id for s in policyset.policy_set()]
    assert len(ids) == len(set(ids))
    assert all(i == i.lower() and " " not in i and "_" not in i for i in ids)


def test_the_gh_read_allowlist_is_the_rfc_list() -> None:
    assert tuple(v.verb for v in policyset.gh_allowlist()) == GH_ALLOW_VERBS


def test_gh_allow_statement_ids_are_generated_from_the_verbs() -> None:
    ids = [s.id for s in policyset.policy_statements(home="/h") if s.effect == "allow"]
    assert ids == [f"allow-gh-{verb.replace(' ', '-')}" for verb in GH_ALLOW_VERBS]


def test_per_agent_denies_and_exemption() -> None:
    assert policyset.agent_permission_denies() == AGENT_PERMISSION_DENIES
    assert policyset.agent_permission_exempt() == ("devops",)


def test_data_file_version_is_still_1() -> None:
    assert load_rules().version == 1


# guard-state.json.
STATE_TOP_LEVEL = [
    "schema",
    "consents",
    "files",
    "gitconfig",
    "git_config",
    "opencode_config",
    "opencode_policies",
    "agent_permissions",
    "repo_hooks",
    "guard_version",
]


def test_guard_state_top_level_keys() -> None:
    assert list(state.GuardState().to_dict()) == STATE_TOP_LEVEL
    assert state.SCHEMA == 1


def test_guard_state_entry_shapes() -> None:
    st = state.GuardState()
    st.consent("g2", "accepted", "2026-11-02")
    st.record_file("/p", b"x")
    st.record_gitconfig("/f", "/v")
    st.record_git_config("/f", "k", "v", "global")
    st.record_policy("i", "tool.use", "r", "deny", preexisting=False)
    st.record_permission("a", "permission.carter_push", "deny", preexisting=False)
    assert list(st.consents["g2"]) == ["decision", "date", "rev"] and st.consents["g2"]["rev"] == 1
    assert list(st.files[0]) == ["path", "sha256"] and st.files[0]["sha256"].startswith("sha256:")
    assert list(st.gitconfig or {}) == ["file", "key", "value"]
    assert (st.gitconfig or {})["key"] == "include.path"
    assert list(st.git_config[0]) == ["file", "key", "value", "scope"]
    assert list(st.opencode_policies[0]) == ["id", "action", "resource", "effect", "preexisting"]
    assert list(st.agent_permissions[0]) == ["agent", "key", "value", "preexisting"]


# Plugin, gate and isolation names. A rename changes what is written to the user's machine
# (isolation.json, plugin-status, error codes).

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from carter.identity.errors import registry  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


# the 15 rule ids of a gate decision. 11 are the `forbidden[].id`, 4 are gate-only.
FORBIDDEN_IDS = (
    "commit-flags",
    "staging",
    "push-verbs",
    "env-overrides",
    "git-config-writes",
    "config-flags",
    "plumbing",
    "other-verbs",
    "human-only-carter",
    "credential-paths",
    "control-files",
)
GATE_ONLY_IDS = ("dynamic-command", "interpreter-git", "git-alias", "gate-input")
# the consent group a rule belongs to (`--skip-groups`). Everything not listed is `g2`.
GROUP_OF_RULE = {"credential-paths": "read-edit-denies", "control-files": "config-edit"}
GROUP_OF_VERB = {
    "sudo": "sudo-docker",
    "docker": "sudo-docker",
    "podman": "sudo-docker",
    "doas": "sudo-docker",  # gate additions: the same privilege class
    "pkexec": "sudo-docker",
}

# isolation.json schema v1. Unknown or missing keys mean the file is invalid.
ISOLATION_TOP_LEVEL = (
    "schema_version",
    "env",
    "git_config",
    "blocking_git_config",
    "pollution",
    "plugin",
)
ISOLATION_ENV_KEYS = ("set", "delete")
ISOLATION_POLLUTION_KEYS = ("agent_signals", "human_signals", "markers")
ISOLATION_MARKER_KEYS = ("env", "git_config")
ISOLATION_PLUGIN_KEYS = (
    "b_enabled",
    "b_caller",
    "broker_args",
    "b_git",
    "b_gh",
    "python_path",
    "carter_path",
    "gate_args",
    "env_args",
    "pat_file",
    "pat_prefix",
    "gh_token_dummy",
    "declined_groups",
    "self_test_ms",
    "gate_timeout_ms",
    "env_timeout_ms",
    "status_dir",
)
# the defaults the data file carries for the `plugin` block.
PLUGIN_DEFAULTS = {
    "gate_args": ["-I", "-m", "carter.gate", "--json"],
    "env_args": ["-I", "-m", "carter.identity.env", "--json"],
    "pat_prefix": "github_pat_",
    "self_test_ms": 2000,
    "gate_timeout_ms": 1000,
    "env_timeout_ms": 2000,
}
BLOCKING_GIT_CONFIG = [["commit.gpgsign", "true"], ["gpg.format", "ssh"]]

# plugin-status/<pid>.json. Names only, no env values.
STATUS_KEYS = (
    "schema_version",
    "pid",
    "boot",
    "instance",
    "plugin_version",
    "opencode_version",
    "state",
    "since",
    "failed_reason",
    "isolation_sha256",
    "flags",
)
STATUS_STATES = ("unproven", "passed", "failed")
STATUS_FLAGS = ("pat-dummy", "polluted", "count-malformed", "sign-unavailable", "config-error")

# `identity env`.
TIER_ENV_KEYS = ("schema_version", "tier", "cap", "effective", "require_tier", "reason")
TIER_REASONS = (None, "config-error", "signing-not-built", "tier-required")


def test_forbidden_ids_and_gate_only_ids() -> None:
    from carter.identity import rules

    assert tuple(f.id for f in load_rules().forbidden) == FORBIDDEN_IDS
    assert tuple(g.id for g in rules.gate_rules()) == GATE_ONLY_IDS


def test_every_forbidden_class_has_a_group_and_a_hint() -> None:
    for f in load_rules().forbidden:
        assert f.group == GROUP_OF_RULE.get(f.id, "g2"), f.id
        assert f.hint and "\n" not in f.hint and not f.hint.startswith("!"), f.id
        assert "`!" not in f.hint, f.id  # commands are shown without a leading `!`
    other = next(f for f in load_rules().forbidden if f.id == "other-verbs")
    assert dict(other.item_groups) == GROUP_OF_VERB


def test_the_plugin_defaults_of_the_data_file() -> None:
    from carter.identity import rules

    defaults = rules.plugin_defaults()
    for key, value in PLUGIN_DEFAULTS.items():
        assert defaults[key] == value, key
    assert defaults["status_dir"] == "run/plugin-status"
    assert defaults["gh_token_dummy"] and not defaults["gh_token_dummy"].startswith("github_pat_")
    assert set(defaults) == {
        *PLUGIN_DEFAULTS,
        "gh_token_dummy",
        "status_dir",
        "broker_args",
        "b_caller",
    }


def test_the_isolation_schema_names() -> None:
    iso = pytest.importorskip("carter.identity.isolation")
    doc = iso.render(
        home="/home/example",
        python_path="/opt/carter/bin/python",
        carter_path="/opt/carter/bin/carter",
        false_path="/usr/bin/false",
    )
    assert tuple(doc) == tuple(sorted(ISOLATION_TOP_LEVEL))  # canonical order is sorted
    assert tuple(doc["env"]) == tuple(sorted(ISOLATION_ENV_KEYS))
    assert tuple(doc["pollution"]) == tuple(sorted(ISOLATION_POLLUTION_KEYS))
    assert tuple(doc["pollution"]["markers"]) == tuple(sorted(ISOLATION_MARKER_KEYS))
    assert tuple(doc["plugin"]) == tuple(sorted(ISOLATION_PLUGIN_KEYS))
    assert doc["schema_version"] == 2  # includes the broker keys in `plugin`
    assert doc["blocking_git_config"] == BLOCKING_GIT_CONFIG


def test_status_and_tier_names_are_in_the_shared_vector_file() -> None:
    vectors = json.loads((REPO / "tests/data/plugin_vectors.json").read_text())
    assert tuple(vectors["status"]["keys"]) == STATUS_KEYS
    assert tuple(vectors["status"]["states"]) == STATUS_STATES
    assert tuple(vectors["status"]["flags"]) == STATUS_FLAGS
    assert tuple(vectors["tier"]["env_keys"]) == TIER_ENV_KEYS
    # the reasons are a superset of these (see test_the_signing_reasons_and_shape below)
    assert set(TIER_REASONS) - {"signing-not-built"} <= set(vectors["tier"]["reasons"])
    assert set(vectors) >= {"ad1", "pollution", "count", "marker", "isolation", "tier", "status"}


# Identity and signing names. A rename changes what is written to the user's machine or what the
# model reads.

STDLIB_ONLY_2B = (
    "carter/identity/payload.py",
    "carter/identity/mirror.py",
)  # run in the plugin path

# host files, relative to the home directory.
H2_PATHS = {
    "shim": ".carter/bin/carter-ssh-sign",
    "allowed_signers": ".carter/hooks/allowed_signers",
    "pidfile": ".carter/run/agent.pid",
    "lock": ".carter/run/unlock.lock",
    "guard_log": ".carter/state/audit/guard.log",
}
H2_SIGNING_DEFAULTS = {"ttl": "", "ssh_bin_dir": "/usr/bin"}
H2_SOCKET_LIMITS = {"darwin": 104, "linux": 108}

# `identity env`, additive `signing` object (present only at effective t2 with reason null).
SIGNING_KEYS = ("env", "git_config", "fingerprint")
SIGNING_ENV_KEYS = ("GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "CARTER_IDENTITY")
SIGNING_GIT_CONFIG_KEYS = ("gpg.format", "user.signingkey", "gpg.ssh.program", "commit.gpgsign")
TIER_REASONS_2B = (
    None,
    "config-error",
    "tier-required",
    "key-missing",
    "fingerprint-mismatch",
    "shim-missing",
    "human-identity-invalid",
    "review-mode",  # a review run makes no commits
)

# the keys of Carter's gitconfig, and the fragment name rule.
CARTER_GIT_KEYS = ("carter.tier", "carter.llmEmail", "carter.llmFingerprint")

# the shim's allow-list and the minimum versions. The data lives in g2_rules.json.
SHIM_Y_OPS = ("verify", "find-principals", "check-novalidate")
MIN_GIT_SIGNING = (2, 40)
MIN_OPENSSH = (8, 4)

# the unlock and lock commands (the rest of the identity group arrives in 13-17).
IDENTITY_SUBCOMMANDS = ("add", "show", "verify", "unlock", "lock", "remove", "env")
UNLOCK_OPTIONS = ("--extend", "--ttl")
LOCK_OPTIONS = ("--all",)

# the flags `carter commit` refuses.
COMMIT_REFUSED_FLAGS = (
    "--no-verify",
    "-n",
    "--no-gpg-sign",
    "-S<arg>",
    "--gpg-sign=<arg>",
    "-s",
    "--signoff",
    "--author",
)

# Consent revisions.
CONSENT_REVS = {
    "g2": 3,
    "hooks": 2,
    "sudo-docker": 1,
    "read-edit-denies": 1,
    "config-edit": 1,
    "alias": 1,
    "repo_hooks": 2,
}
ALIAS_VALUE = '!cd "${GIT_PREFIX:-.}" && carter commit'

# the hook that raises each guard code (prepare-commit-msg holds every reject check).
GUARD_CODE_WHERE_2B = {
    "E-GUARD-NOIDENT": "prepare-commit-msg",
    "E-GUARD-COMMITTER": "prepare-commit-msg",
    "E-GUARD-SIGNCFG": "prepare-commit-msg",
    "E-GUARD-NOSIGN": "prepare-commit-msg",
    "E-GUARD-TRAILER": "commit-msg",
    "E-GUARD-UNSIGNED": "post-commit",
}


@pytest.mark.parametrize("path", STDLIB_ONLY_2B)
def test_the_runtime_modules_import_only_the_standard_library(path: str) -> None:
    import ast
    import sys

    file = REPO / path
    if not file.exists():
        pytest.skip(f"{path} arrives later")
    tree = ast.parse(file.read_text())
    for node in ast.walk(tree):
        names = (
            [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom) and node.level == 0
            else []
        )
        for name in names:
            top = name.split(".")[0]
            assert top in sys.stdlib_module_names or top == "carter", f"{path} imports {name}"
            assert not name.startswith(("carter.cli", "carter.guard", "click")), name


def test_the_signing_defaults_of_the_config_schema() -> None:
    from carter.identity.schema import Signing

    s = Signing()
    assert (s.ttl, s.ssh_bin_dir) == (
        H2_SIGNING_DEFAULTS["ttl"],
        H2_SIGNING_DEFAULTS["ssh_bin_dir"],
    )


def test_the_host_file_paths(tmp_path: Path) -> None:
    mod = pytest.importorskip("carter.identity.agent")
    shim = pytest.importorskip("carter.identity.shim")
    assert shim.shim_path(tmp_path) == tmp_path / H2_PATHS["shim"]
    assert shim.allowed_signers_path(tmp_path) == tmp_path / H2_PATHS["allowed_signers"]
    assert mod.pidfile_path(tmp_path) == tmp_path / H2_PATHS["pidfile"]
    assert mod.lock_path(tmp_path) == tmp_path / H2_PATHS["lock"]
    assert mod.SOCKET_LIMITS == H2_SOCKET_LIMITS


def test_the_signing_reasons_and_shape_are_in_the_shared_vector_file() -> None:
    vectors = json.loads((REPO / "tests/data/plugin_vectors.json").read_text())
    assert tuple(vectors["tier"]["reasons"]) == TIER_REASONS_2B
    assert tuple(vectors["tier"]["env_keys"]) == TIER_ENV_KEYS  # schema stays 1, key set unchanged
    assert tuple(vectors["signing"]["keys"]) == SIGNING_KEYS
    assert tuple(vectors["signing"]["env_keys"]) == SIGNING_ENV_KEYS
    assert tuple(vectors["signing"]["git_config_keys"]) == SIGNING_GIT_CONFIG_KEYS


def test_the_payload_block_has_the_frozen_shape(tmp_path: Path) -> None:
    payload = pytest.importorskip("carter.identity.payload")
    assert payload.SIGNING_KEYS == SIGNING_KEYS
    assert payload.SIGNING_ENV_KEYS == SIGNING_ENV_KEYS
    assert payload.SIGNING_GIT_CONFIG_KEYS == SIGNING_GIT_CONFIG_KEYS
    assert tuple(r for r in TIER_REASONS_2B if r) == payload.REASONS


def test_the_carter_git_keys() -> None:
    mirror = pytest.importorskip("carter.identity.mirror")
    assert mirror.CARTER_KEYS == CARTER_GIT_KEYS


def test_the_shim_allow_list_and_the_minimum_versions() -> None:
    shim = pytest.importorskip("carter.identity.shim")
    assert tuple(load_rules().shim_y_ops) == SHIM_Y_OPS
    assert shim.MIN_GIT_SIGNING == MIN_GIT_SIGNING
    assert shim.MIN_OPENSSH == MIN_OPENSSH


def test_the_unlock_and_lock_commands() -> None:
    cli = pytest.importorskip("carter.identity_cli")
    group = cli.identity
    assert set(group.commands) <= set(IDENTITY_SUBCOMMANDS)
    unlock = {o.opts[0] for o in group.commands["unlock"].params if o.opts[0].startswith("--")}
    lock = {o.opts[0] for o in group.commands["lock"].params if o.opts[0].startswith("--")}
    assert unlock - {"--help"} == set(UNLOCK_OPTIONS)
    assert lock - {"--help"} == set(LOCK_OPTIONS)


def test_the_refused_commit_flags() -> None:
    commit = pytest.importorskip("carter.identity.commit")
    assert tuple(commit.REFUSED_FLAGS) == COMMIT_REFUSED_FLAGS


def test_the_alias_value_has_no_duplicated_arguments() -> None:
    assert ALIAS_VALUE.count('"$@"') == 0  # git appends "$@" itself (8, )


def test_the_guard_codes_name_the_hook_that_raises_them() -> None:
    reg = registry()
    for code, hook in GUARD_CODE_WHERE_2B.items():
        assert reg[code].where.startswith(hook), code


SIGNING_ENV_KEYS_B = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "CARTER_IDENTITY",
)
# One definition of a usable human identity; the link states and the cache.
HUMAN_PROBLEMS = ("missing-name", "missing-email", "bad-name", "bad-email", "llm-email", "fallback")
HUMAN_FALLBACK_EMAILS = ("carter-bot@*",)  # alone; narrowed by the maintainer
HUMAN_FALLBACK_PAIRS = (("Carter", "state@carter.invalid"),)  # only together
LINK_CACHE_REL = ".carter/run/coauthor-link.json"
LINK_CACHE_TTL_S = 7 * 24 * 3600
LINK_STATES = ("noreply", "verified")
ADD_ROLE_CHOICES = ("co-author", "author")


def test_the_role_b_signing_env_keys_and_the_role_a_keys_stay() -> None:
    payload = pytest.importorskip("carter.identity.payload")
    assert payload.SIGNING_ENV_KEYS_B == SIGNING_ENV_KEYS_B
    assert payload.SIGNING_ENV_KEYS == SIGNING_ENV_KEYS
    assert set(SIGNING_ENV_KEYS) < set(SIGNING_ENV_KEYS_B)
    vectors = json.loads((REPO / "tests/data/plugin_vectors.json").read_text())
    assert tuple(vectors["signing"]["env_keys_role_b"]) == SIGNING_ENV_KEYS_B


def test_the_reasons_replace_role_b_not_built() -> None:
    payload = pytest.importorskip("carter.identity.payload")
    assert "role-b-not-built" not in payload.REASONS
    assert payload.REASONS[-2] == "human-identity-invalid"  # review-mode comes after it


def test_the_human_identity_problems_and_fallbacks() -> None:
    from carter.identity.rules import human_identity_rules

    coauthor = pytest.importorskip("carter.identity.coauthor")
    assert coauthor.PROBLEMS == HUMAN_PROBLEMS
    rules = human_identity_rules()
    assert tuple(rules["fallback_emails"]) == HUMAN_FALLBACK_EMAILS
    assert tuple(tuple(p) for p in rules["fallback_pairs"]) == HUMAN_FALLBACK_PAIRS
    vectors = json.loads((REPO / "tests/data/human_identity_vectors.json").read_text())
    assert {c["problem"] for c in vectors["cases"]} - {""} == set(HUMAN_PROBLEMS)


def test_the_link_cache_name_ttl_and_states() -> None:
    coauthor = pytest.importorskip("carter.identity.coauthor")
    assert coauthor.LINK_CACHE_REL == LINK_CACHE_REL
    assert coauthor.LINK_CACHE_TTL_S == LINK_CACHE_TTL_S
    assert coauthor.LINK_STATES == LINK_STATES


def test_identity_add_has_the_role_option() -> None:
    cli = pytest.importorskip("carter.identity_cli")
    add = cli.identity.commands["add"]
    role = next((o for o in add.params if o.opts[0] == "--role"), None)
    assert role is not None
    assert tuple(role.type.choices) == ADD_ROLE_CHOICES


BROKER_ENTRY = ("-I", "-m", "carter.broker_cli")  # the only entry
BROKER_SUBCOMMANDS = ("push", "record")
RECORD_OUTCOMES = ("rejected", "timeout", "aborted", "corrected", "dwell")
BROKER_EXIT_CODES = {"ok": 0, "refused": 1, "usage": 2}
DEVOPS_AGENT = "carter-devops"
# Python judges the dwell; the floor is 500 ms, configurable upward only.
DWELL = {"default": 500, "floor": 500, "cap": 10000, "timeout_ms": 120000}
REJECTIONS_MAX = 3
COUNTER_FILE = "b-rejections.json"
AUDIT_DIR_REL = ("state", "audit")
AUDIT_FILES = ("b.jsonl", "audit.log")
AUDIT_FIELDS = (
    "ts", "root", "session", "agent", "owner_repo", "branch", "range", "commits", "verb",
    "decision", "code", "dwell_ms",
)  # fmt: skip
AUDIT_DECISIONS = (
    "approved",
    "rejected",
    "corrected",
    "timeout",
    "aborted",
    "dwell",
    "refused",
    "error",
)
AUDIT_ROTATE_BYTES = 5 * 1024 * 1024
AUDIT_ROTATE_KEEP = 3
# the plan JSON (common keys, then per verb)
PLAN_COMMON_KEYS = ("approval", "ask", "audit", "branch", "pinned_sha", "repo", "verb")
PLAN_PUSH_KEYS = ("base_label", "commits", "count", "new", "new_branch", "old", "sensitive")
APPROVAL_KEYS = ("min_dwell_ms", "timeout_ms")
ASK_KEYS = ("metadata", "resources")
# isolation.json schema 2
ISOLATION_B_KEYS = ("b_enabled", "b_caller", "broker_args", "b_git", "b_gh")
CONSENT_REV_PLUGIN, CONSENT_REV_BROKER = 2, 3
HEADLESS_PROFILE = "opencode-headless.json"
BROKER_CONFIG_KEYS = ("min_dwell_ms",)  # no home key
BROKER_TS_MAX_LINES, INDEX_TS_MAX_LINES = 200, 80
# where git and gh may be found at install (never PATH at runtime)
TOOL_DIRS = ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin")


def test_the_entry_the_subcommands_and_the_exit_codes() -> None:
    cli = pytest.importorskip("carter.broker_cli")
    assert tuple(cli.OUTCOMES) == RECORD_OUTCOMES
    assert tuple(BROKER_EXIT_CODES.values()) == (cli.EXIT_OK, cli.EXIT_REFUSED, cli.EXIT_USAGE)
    from carter.identity import rules

    assert tuple(rules.plugin_defaults()["broker_args"]) == BROKER_ENTRY
    sub = cli.parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert tuple(sub) == BROKER_SUBCOMMANDS
    for verb in ("push",):
        flags = {o for a in sub[verb]._actions for o in a.option_strings}
        assert {"--plan", "--exec", "--pinned-sha", "--asked-at", "--answered-at"} <= flags
        assert not {"--remote", "--ref", "--url", "--refspec", "--force", "--branch"} & flags


def test_the_dwell_and_timeout_constants() -> None:
    from carter.broker import plan

    assert (
        DWELL["floor"], DWELL["cap"], DWELL["timeout_ms"]
    ) == (plan.DWELL_FLOOR_MS, plan.DWELL_CAP_MS, plan.TIMEOUT_MS)  # fmt: skip
    assert plan.DWELL_FLOOR_MS >= 500
    from carter.identity.schema import Broker

    assert Broker().min_dwell_ms == DWELL["default"]


def test_the_counter_file_and_limit() -> None:
    from carter.broker import counter

    assert (counter.MAX_REJECTIONS, counter.FILE) == (REJECTIONS_MAX, COUNTER_FILE)


def test_the_only_caller() -> None:
    import carter.broker as broker
    from carter.identity import rules

    assert broker.DEVOPS_AGENT == DEVOPS_AGENT == rules.plugin_defaults()["b_caller"]
    assert broker.VERBS == ("push",)  # PRs are opened with gh; widening B needs a new ADR


def test_the_audit_store() -> None:
    from carter.broker import audit

    assert tuple(audit.FIELDS) == AUDIT_FIELDS and tuple(audit.DECISIONS) == AUDIT_DECISIONS
    assert (audit.B_LOG, audit.OPS_LOG) == AUDIT_FILES
    assert (audit.ROTATE_BYTES, audit.ROTATE_KEEP) == (AUDIT_ROTATE_BYTES, AUDIT_ROTATE_KEEP)
    assert audit.audit_dir(Path("/c")) == Path("/c").joinpath(*AUDIT_DIR_REL)


def test_the_plan_json_keys(tmp_path: Path) -> None:
    broker_world = pytest.importorskip("broker.world")
    from carter.broker import plan

    world = broker_world.World(tmp_path)
    try:
        world.commit("a.txt")
        built = plan.build_push_plan(world.repo, world.ctx, broker_world.DEVOPS, world.server_env())
        doc = plan.push_plan_json(built, world.ctx, broker_world.DEVOPS)
        assert set(doc) == {*PLAN_COMMON_KEYS, *PLAN_PUSH_KEYS}
        assert tuple(doc["approval"]) == APPROVAL_KEYS and tuple(sorted(doc["ask"])) == ASK_KEYS
    finally:
        world.close()


def test_the_isolation_broker_keys_and_the_consent_revisions() -> None:
    from carter.guard import consent

    assert set(ISOLATION_B_KEYS) <= set(ISOLATION_PLUGIN_KEYS)
    assert (consent.PLUGIN_REV, consent.BROKER_REV) == (CONSENT_REV_PLUGIN, CONSENT_REV_BROKER)
    assert {g.id: g.rev for g in policyset.consent_groups()}["g2"] == CONSENT_REV_BROKER
    g2 = next(g for g in policyset.consent_groups() if g.id == "g2")
    assert "not a security boundary" in " ".join(g2.explain)


def test_the_headless_profile_name_and_content() -> None:
    from carter.guard import plugin
    from carter.install import paths

    assert paths.headless_profile_path(None).name == HEADLESS_PROFILE
    doc = json.loads(plugin.render_headless())
    assert list(doc) == ["agents"] and list(doc["agents"]) == [DEVOPS_AGENT]
    assert "policies" not in doc  # a global tool.use policy never matches a plugin tool
    assert {r["action"] for r in doc["agents"][DEVOPS_AGENT]["permissions"]} == set(
        AGENT_PERMISSION_DENIES
    )


def test_the_tool_directories_are_fixed() -> None:
    from carter.guard import plugin

    assert tuple(plugin.TOOL_DIRS) == TOOL_DIRS


def test_the_broker_config_table() -> None:
    from carter.identity.schema import schema_names

    assert schema_names()["broker"] == BROKER_CONFIG_KEYS


def test_the_ts_budgets() -> None:
    assert len((REPO / "carter/plugin/broker.ts").read_text().splitlines()) <= BROKER_TS_MAX_LINES
    assert len((REPO / "carter/plugin/index.ts").read_text().splitlines()) <= INDEX_TS_MAX_LINES


# Review-only CI names.

CIE_WORKFLOW_REL = ".github/workflows/carter-review.yml"
CIE_ENVIRONMENT, CIE_SECRET = "carter-review", "LLM_API_KEY"
CIE_COMMANDS = ("check", "install", "review")
CIE_INSTALL_OPTIONS = ("--comment", "--dry-run", "--force")
CIE_MODES = ("auto", "interactive", "review")
CIE_UNBUILT = ("commit", "scheduled", "ci", "c", "d")  # CI contexts C and D
CIE_MODE_ENV = "CARTER_IDENTITY_MODE"
CIE_ERROR = "E-CI-REVIEW"
CIE_REASON = "review-mode"  # the identity entry's reason
CIE_RULES = tuple(f"CI{n:03d}" for n in range(14))  # CI000-CI013
CIE_DRIVER_ENV = (
    "LLM_API_KEY", "CARTER_CI_BASE_SHA", "CARTER_CI_KEY_ENV", "CARTER_CI_MODEL",
    "CARTER_CI_COMMENT_FILE", "GITHUB_STEP_SUMMARY", "GITHUB_EVENT_PATH",
)  # fmt: skip
CIE_AGENT = "carter-ci-reviewer"
CIE_READ_ONLY = ("read", "glob", "grep")
CIE_COMMENT_JOB = "comment"
CIE_GATE_ITEM = "carter ci install"  # added to the human-only Carter verbs


def test_the_installer_shape() -> None:
    click = pytest.importorskip("click")
    from carter.ci_cli import ci

    assert isinstance(ci, click.Group) and tuple(sorted(ci.commands)) == CIE_COMMANDS
    options = {o for p in ci.commands["install"].params for o in getattr(p, "opts", ())}
    assert set(CIE_INSTALL_OPTIONS) <= options
    import carter.ci as pkg

    assert pkg.WORKFLOW_REL == CIE_WORKFLOW_REL


def test_the_modes_and_their_precedence() -> None:
    from carter.identity import mode

    assert mode.MODES == CIE_MODES and mode.ENV_MODE == CIE_MODE_ENV
    assert tuple(mode.UNBUILT) == CIE_UNBUILT
    assert mode.resolve_mode("", {"CI": "true"}).mode == "review"  # auto in CI
    assert mode.resolve_mode("interactive", {}).mode == "interactive"
    assert mode.resolve_mode("review", {CIE_MODE_ENV: "interactive"}).source == "env"


def test_the_refusal_code_and_the_reason() -> None:
    from carter.identity import payload

    entry = registry()[CIE_ERROR]
    assert "\n" not in entry.message and "review run" in entry.message
    assert CIE_REASON in payload.REASONS


def test_the_secret_and_the_environment() -> None:
    import carter.ci as pkg

    assert (pkg.ENVIRONMENT, pkg.SECRET) == (CIE_ENVIRONMENT, CIE_SECRET)


def test_the_review_agent_can_only_read() -> None:
    from carter.ci import review

    assert review.AGENT == CIE_AGENT and tuple(review.ALLOWED_ACTIONS) == CIE_READ_ONLY
    assert tuple(review.build_profile()["agents"]) == (CIE_AGENT,)
    for name in CIE_DRIVER_ENV:
        assert name in (REPO / "carter/ci/review.py").read_text() or name == "LLM_API_KEY"


def test_the_comment_job_and_the_rule_ids() -> None:
    import carter.ci as pkg
    from carter.ci import check

    assert pkg.COMMENT_JOB == CIE_COMMENT_JOB
    for rule in CIE_RULES:
        assert rule in (check.__doc__ or ""), rule


def test_the_installer_is_a_human_only_carter_verb() -> None:
    data = json.loads((REPO / "carter/identity/g2_rules.json").read_text())
    (cls,) = [c for c in data["forbidden"] if c["id"] == "human-only-carter"]
    assert CIE_GATE_ITEM in cls["items"]
