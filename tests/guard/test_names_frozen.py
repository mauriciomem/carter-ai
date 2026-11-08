# ruff: noqa: E501
"""The 1G names, frozen (plan 003 step 6, F2-F6).

A rename here is a deliberate act: it changes what is written to the user's machine
(OpenCode config statements, ``guard-state.json``) and must go through the architect.
Add to a snapshot only together with the note that explains why.
"""

from __future__ import annotations

from carter.guard import state
from carter.identity import policyset
from carter.identity.rules import load_rules

# F3: the seven consent groups, and which are live in 1G.
GROUPS = ("g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit", "alias", "repo_hooks")

# F5: statement ids per group. gh allows are generated from the allowlist (F4).
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
        "deny-edit-carter-isolation",
        "deny-edit-carter-gitconfig",
        "deny-edit-carter-guard-state",
        "deny-edit-plugin",
    ],
}

# F4 + RFC §4.5 minus `gh status`, which spike 4 showed 403s with a fine-grained read-only PAT.
GH_ALLOW_VERBS = (
    "pr view",
    "pr list",
    "pr diff",
    "pr checks",
    "issue view",
    "issue list",
    "run view",
    "run list",
    "repo view",
    "search",
)

# F6 / D46.
AGENT_PERMISSION_DENIES = ("carter_push", "carter_pr")


def test_consent_groups_are_the_seven_c61_names() -> None:
    assert tuple(g.id for g in policyset.consent_groups()) == GROUPS


def test_every_group_is_live_and_only_alias_is_optional() -> None:
    """2b (H15): `alias` went live at revision 1, optional; the 2a revisions are superseded by
    CONSENT_REVS_2B below."""
    groups = policyset.consent_groups()
    assert all(g.live for g in groups)
    assert [g.id for g in groups if g.optional] == ["alias"]


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


# F2: guard-state.json.
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
    assert list(st.agent_permissions[0]) == ["agent", "key", "value", "preexisting", "form"]


# ---------------------------------------------------------------------------------------------
# Slice 2a (plan 004 step 8, G1-G19), frozen at the start of step 10 and extended by the step
# that creates each item. A rename here is a deliberate act: it changes what is written to the
# user's machine (isolation.json, plugin-status, error codes) and goes through the architect.
# ---------------------------------------------------------------------------------------------

import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from carter.identity.errors import registry  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# G1/G2: module and file paths. Items created by a later step are skipped (with the step) until
# they exist; set CARTER_NAMES_STRICT=1 (step 37) to make a missing one a failure.
MODULES_2A = {
    "carter/identity/isolation.py": "step 11",
    "carter/identity/pollution.py": "step 10",
    "carter/identity/env.py": "step 15",
    "carter/plugin/core.ts": "step 9",
    "carter/plugin/index.ts": "step 16",
    "carter/gate/__init__.py": "step 18",
    "carter/gate/__main__.py": "step 21",
    "carter/gate_cli.py": "step 21",
    "carter/guard/plugin.py": "step 26",
    "carter/guard/hooks.py": "step 24",
    "carter/guard/repohooks.py": "step 25",
    "carter/guard/probe.py": "step 31",
    "carter/guard/templates/carter-guard.sh": "step 22",
}

# G7: the 15 rule ids of a gate decision. 11 are the `forbidden[].id`, 4 are gate-only.
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
# G7: the consent group a rule belongs to (`--skip-groups`). Everything not listed is `g2`.
GROUP_OF_RULE = {"credential-paths": "read-edit-denies", "control-files": "config-edit"}
GROUP_OF_VERB = {
    "sudo": "sudo-docker",
    "docker": "sudo-docker",
    "podman": "sudo-docker",
    "doas": "sudo-docker",  # gate additions: the same privilege class
    "pkexec": "sudo-docker",
}

# G4: isolation.json schema v1. Unknown or missing keys mean the file is invalid.
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
# G4/G16: the defaults the data file carries for the `plugin` block.
PLUGIN_DEFAULTS = {
    "gate_args": ["-I", "-m", "carter.gate", "--json"],
    "env_args": ["-I", "-m", "carter.identity.env", "--json"],
    "pat_prefix": "github_pat_",
    "self_test_ms": 2000,
    "gate_timeout_ms": 1000,
    "env_timeout_ms": 2000,
}
BLOCKING_GIT_CONFIG = [["commit.gpgsign", "true"], ["gpg.format", "ssh"]]

# G5: plugin-status/<pid>.json. Names only, no env values.
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

# G13: `identity env` (2a part).
TIER_ENV_KEYS = ("schema_version", "tier", "cap", "effective", "require_tier", "reason")
TIER_REASONS = (None, "config-error", "signing-not-built", "tier-required")

# G14: raised live in 2a, with the slice tag after the re-tags.
ERROR_SLICES_2A = {
    "E-ISOLATION-MISSING": "2a",
    "E-SELFTEST": "2a",
    "E-GATE": "2a",
    "E-GATE-FAIL": "2a",
    "E-PUSH-GUARD": "2a",
    "E-PUSH-ISOLATED": "2a",
    "E-SSH-ISOLATED": "2a",
    "E-GIT-OLD": "2a",
    "E-OPENCODE-VERSION": "2a",
    "E-SIGN-UNAVAILABLE": "2a",  # re-tagged from 2b
    "E-TIER-CAPPED": "2a",
    "E-TIER-REQUIRED": "1",
    "E-CONFIG": "1",
    "E-GUARD-T01SIGN": "2a",
    "E-PROBE-SCOPE": "2a",  # new
    "E-FALSE-MISSING": "2a",  # new
}
# Re-tagged to 2b: their hooks (commit-msg, post-commit) ship in 2b.
ERROR_SLICES_2B = (
    "E-GUARD-NOIDENT",
    "E-GUARD-COMMITTER",
    "E-GUARD-SIGNCFG",
    "E-GUARD-TRAILER",
    "E-GUARD-UNSIGNED",
)


@pytest.mark.parametrize("path", sorted(MODULES_2A), ids=str)
def test_2a_module_paths_exist_once_their_step_has_run(path: str) -> None:
    if (REPO / path).exists():
        return
    if os.environ.get("CARTER_NAMES_STRICT") == "1":
        pytest.fail(f"{path} ({MODULES_2A[path]}) is frozen but missing")
    pytest.skip(f"{path} arrives in {MODULES_2A[path]}")


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


def test_the_data_file_has_no_reserved_keys_left() -> None:
    data = json.loads((REPO / "carter/identity/g2_rules.json").read_text())
    assert data["reserved"] == []
    assert data["isolation_vars"]


def test_error_codes_of_2a_and_their_slice_tags() -> None:
    reg = registry()
    for code, slice_ in ERROR_SLICES_2A.items():
        assert reg[code].slice == slice_, code
    for code in ERROR_SLICES_2B:
        assert reg[code].slice == "2b", code
    assert reg["E-FALSE-MISSING"].message == (
        "no root-owned `false` found at /usr/bin/false or /bin/false; G2 cannot be installed"
    )
    assert "inside an agent shell" in reg["E-PROBE-SCOPE"].message


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
    assert doc["schema_version"] == 2  # slice B (B9): the broker keys in `plugin`
    assert doc["blocking_git_config"] == BLOCKING_GIT_CONFIG


def test_status_and_tier_names_are_in_the_shared_vector_file() -> None:
    vectors = json.loads((REPO / "tests/data/plugin_vectors.json").read_text())
    assert tuple(vectors["status"]["keys"]) == STATUS_KEYS
    assert tuple(vectors["status"]["states"]) == STATUS_STATES
    assert tuple(vectors["status"]["flags"]) == STATUS_FLAGS
    assert tuple(vectors["tier"]["env_keys"]) == TIER_ENV_KEYS
    # the reasons were extended by 2b (H3, see test_h3 below); the 2a ones are still a subset
    assert set(TIER_REASONS) - {"signing-not-built"} <= set(vectors["tier"]["reasons"])
    assert set(vectors) >= {"ad1", "pollution", "count", "marker", "isolation", "tier", "status"}


# ---------------------------------------------------------------------------------------------
# Slice 2b (plan 005 step 6, H1-H16), frozen at the start of step 7 and extended by the step that
# creates each item. Items created by a later step are skipped (with the step) until they exist
# (CARTER_NAMES_STRICT=1 turns a missing one into a failure); items whose *value* changes in a
# later step are strict xfails that flip when the step lands. A rename here goes through the
# architect: it changes what is written to the user's machine or what the model reads.
# ---------------------------------------------------------------------------------------------

# H1: module and file paths.
MODULES_2B = {
    "carter/identity/payload.py": "step 8",
    "carter/identity/shim.py": "step 9",
    "carter/identity/templates/carter-ssh-sign.sh": "step 9",
    "carter/identity/agent.py": "step 10",
    "carter/identity_cli.py": "step 11",
    "carter/identity/mirror.py": "step 13",
    "carter/identity/github.py": "step 14",
    "carter/identity/commit.py": "step 21",
    "carter/commit_cli.py": "step 22",
}
STDLIB_ONLY_2B = (
    "carter/identity/payload.py",
    "carter/identity/mirror.py",
)  # run in the plugin path

# H2: host files, relative to the home directory.
H2_PATHS = {
    "shim": ".carter/bin/carter-ssh-sign",
    "allowed_signers": ".carter/hooks/allowed_signers",
    "pidfile": ".carter/run/agent.pid",
    "lock": ".carter/run/unlock.lock",
    "guard_log": ".carter/run/guard.log",
}
H2_SIGNING_DEFAULTS = {"ttl": "", "ssh_bin_dir": "/usr/bin"}
H2_SOCKET_LIMITS = {"darwin": 104, "linux": 108}

# H3: `identity env`, additive `signing` object (present only at effective t2 with reason null).
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
    "human-identity-invalid",  # 2c (K3): replaces role-b-not-built
    "review-mode",  # CI-E (plan 008 C4): context E makes no commits
)

# H5: the keys of Carter's gitconfig, and the fragment name rule (step 13).
CARTER_GIT_KEYS = ("carter.tier", "carter.llmEmail", "carter.llmFingerprint")

# H8/H9: the shim's allow-list and the minimum versions. The data lives in g2_rules.json.
SHIM_Y_OPS = ("verify", "find-principals", "check-novalidate")
MIN_GIT_SIGNING = (2, 40)
MIN_OPENSSH = (8, 4)

# H10/H12: the unlock and lock commands (the rest of the identity group arrives in 13-17).
IDENTITY_SUBCOMMANDS = ("add", "show", "verify", "unlock", "lock", "remove", "env")
UNLOCK_OPTIONS = ("--extend", "--ttl")
LOCK_OPTIONS = ("--all",)

# H14: the flags `carter commit` refuses (step 21).
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

# H15: consent revisions after 2b (step 19); slice B (plan 007 B9) moves `g2` to 3.
CONSENT_REVS_2B = {
    "g2": 3,
    "hooks": 2,
    "sudo-docker": 1,
    "read-edit-denies": 1,
    "config-edit": 1,
    "alias": 1,
    "repo_hooks": 2,
}
LIVE_GROUPS_2B = (
    "g2",
    "hooks",
    "sudo-docker",
    "read-edit-denies",
    "config-edit",
    "alias",
    "repo_hooks",
)
ALIAS_VALUE = '!cd "${GIT_PREFIX:-.}" && carter commit'

# H7/H16: the hook that raises each guard code (prepare-commit-msg holds every reject check).
GUARD_CODE_WHERE_2B = {
    "E-GUARD-NOIDENT": "prepare-commit-msg",
    "E-GUARD-COMMITTER": "prepare-commit-msg",
    "E-GUARD-SIGNCFG": "prepare-commit-msg",
    "E-GUARD-T01SIGN": "prepare-commit-msg",
    "E-GUARD-TRAILER": "commit-msg",
    "E-GUARD-UNSIGNED": "post-commit",
}

# H16: raised live in 2b, and the two new codes.
ERRORS_LIVE_2B = (
    "E-SIGN-LOCKED",
    "E-SIGN-NOAGENT",
    "E-SIGN-HUMAN-FALLBACK",
    "E-SIGN-AGENT-REFUSE",
    "E-SHIM-REFUSED",
    "E-SSH-OLD",
    "E-UNLOCK-TTY",
    "E-UNLOCK-OPENCODE",
    "E-UNLOCK-PATH",
    "E-UNLOCK-BADPASS",
    "E-IDENTITY-CHECK",
    "E-GITHUB-UNREACHABLE",
)
ERRORS_NEW_2B = ("E-IDENTITY-CHECK", "E-GITHUB-UNREACHABLE")
AGENT_FACING = (
    "E-SIGN-LOCKED",
    "E-SIGN-NOAGENT",
    "E-SIGN-UNAVAILABLE",
    "E-SIGN-AGENT-REFUSE",
    "E-SHIM-REFUSED",
    "E-GUARD-NOIDENT",
    "E-GUARD-COMMITTER",
    "E-GUARD-SIGNCFG",
    "E-GUARD-TRAILER",
    "E-GUARD-UNSIGNED",
    "E-GUARD-T01SIGN",
    "E-TIER-CAPPED",
    "E-TIER-REQUIRED",
)


@pytest.mark.parametrize("path", sorted(MODULES_2B), ids=str)
def test_2b_module_paths_exist_once_their_step_has_run(path: str) -> None:
    if (REPO / path).exists():
        return
    if os.environ.get("CARTER_NAMES_STRICT") == "1":
        pytest.fail(f"{path} ({MODULES_2B[path]}) is frozen but missing")
    pytest.skip(f"{path} arrives in {MODULES_2B[path]}")


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


def test_h2_the_signing_defaults_of_the_config_schema() -> None:
    from carter.identity.schema import Signing

    s = Signing()
    assert (s.ttl, s.ssh_bin_dir) == (
        H2_SIGNING_DEFAULTS["ttl"],
        H2_SIGNING_DEFAULTS["ssh_bin_dir"],
    )


def test_h2_the_host_file_paths(tmp_path: Path) -> None:
    mod = pytest.importorskip("carter.identity.agent")
    shim = pytest.importorskip("carter.identity.shim")
    assert shim.shim_path(tmp_path) == tmp_path / H2_PATHS["shim"]
    assert shim.allowed_signers_path(tmp_path) == tmp_path / H2_PATHS["allowed_signers"]
    assert mod.pidfile_path(tmp_path) == tmp_path / H2_PATHS["pidfile"]
    assert mod.lock_path(tmp_path) == tmp_path / H2_PATHS["lock"]
    assert mod.SOCKET_LIMITS == H2_SOCKET_LIMITS


def test_h3_the_signing_reasons_and_shape_are_in_the_shared_vector_file() -> None:
    vectors = json.loads((REPO / "tests/data/plugin_vectors.json").read_text())
    assert tuple(vectors["tier"]["reasons"]) == TIER_REASONS_2B
    assert tuple(vectors["tier"]["env_keys"]) == TIER_ENV_KEYS  # schema stays 1, key set unchanged
    assert tuple(vectors["signing"]["keys"]) == SIGNING_KEYS
    assert tuple(vectors["signing"]["env_keys"]) == SIGNING_ENV_KEYS
    assert tuple(vectors["signing"]["git_config_keys"]) == SIGNING_GIT_CONFIG_KEYS


def test_h3_the_payload_block_has_the_frozen_shape(tmp_path: Path) -> None:
    payload = pytest.importorskip("carter.identity.payload")
    assert payload.SIGNING_KEYS == SIGNING_KEYS
    assert payload.SIGNING_ENV_KEYS == SIGNING_ENV_KEYS
    assert payload.SIGNING_GIT_CONFIG_KEYS == SIGNING_GIT_CONFIG_KEYS
    assert tuple(r for r in TIER_REASONS_2B if r) == payload.REASONS


def test_h5_the_carter_git_keys() -> None:
    mirror = pytest.importorskip("carter.identity.mirror")
    assert mirror.CARTER_KEYS == CARTER_GIT_KEYS


def test_h8_h9_the_shim_allow_list_and_the_minimum_versions() -> None:
    shim = pytest.importorskip("carter.identity.shim")
    assert tuple(load_rules().shim_y_ops) == SHIM_Y_OPS
    assert shim.MIN_GIT_SIGNING == MIN_GIT_SIGNING
    assert shim.MIN_OPENSSH == MIN_OPENSSH


def test_h10_h12_the_unlock_and_lock_commands() -> None:
    cli = pytest.importorskip("carter.identity_cli")
    group = cli.identity
    assert set(group.commands) <= set(IDENTITY_SUBCOMMANDS)
    unlock = {o.opts[0] for o in group.commands["unlock"].params if o.opts[0].startswith("--")}
    lock = {o.opts[0] for o in group.commands["lock"].params if o.opts[0].startswith("--")}
    assert unlock - {"--help"} == set(UNLOCK_OPTIONS)
    assert lock - {"--help"} == set(LOCK_OPTIONS)


def test_h14_the_refused_commit_flags() -> None:
    commit = pytest.importorskip("carter.identity.commit")
    assert tuple(commit.REFUSED_FLAGS) == COMMIT_REFUSED_FLAGS


def test_h15_consent_revisions_and_live_groups_after_2b() -> None:
    assert {g.id: g.rev for g in policyset.consent_groups()} == CONSENT_REVS_2B
    assert tuple(g.id for g in policyset.consent_groups() if g.live) == LIVE_GROUPS_2B


def test_h15_the_alias_value_has_no_duplicated_arguments() -> None:
    assert ALIAS_VALUE.count('"$@"') == 0  # git appends "$@" itself (spike B 8, erratum R1)


def test_h7_the_guard_codes_name_the_hook_that_raises_them() -> None:
    reg = registry()
    for code, hook in GUARD_CODE_WHERE_2B.items():
        assert reg[code].where.startswith(hook), code


def test_h16_the_2b_error_codes_exist_with_the_2b_tag() -> None:
    reg = registry()
    for code in ERRORS_LIVE_2B:
        assert reg[code].slice == "2b", code
    for code in ERRORS_NEW_2B:
        assert reg[code].message and "\n" not in reg[code].message, code
    assert "2.40" in reg["E-GIT-OLD"].message and "2.54" in reg["E-GIT-OLD"].message
    assert "E-SIGN-UNAVAILABLE" in AGENT_FACING and reg["E-SIGN-UNAVAILABLE"].slice == "2a"


def test_h16_the_current_slice_moves_only_in_step_27() -> None:
    from carter.identity.rules import CURRENT_SLICE

    assert CURRENT_SLICE in (
        "2c",
        "B",
        "CI-E",
    )  # 2c moved it in plan 006 step 11 (K13), B in plan 007


# ---------------------------------------------------------------------------------------------
# Slice 2c (plan 006 step 3, K1-K13), frozen before dependent code. Same rules as 2b above.
# ---------------------------------------------------------------------------------------------

MODULES_2C = {
    "carter/identity/coauthor.py": "step 4",
    "tests/data/human_identity_vectors.json": "step 4",
}
# K5: role b adds the author to the same atomic dict; role a is unchanged.
SIGNING_ENV_KEYS_B = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "CARTER_IDENTITY",
)
# K2: one definition of a usable human identity; K7: the link states and the cache.
HUMAN_PROBLEMS = ("missing-name", "missing-email", "bad-name", "bad-email", "llm-email", "fallback")
HUMAN_FALLBACK_EMAILS = ("carter-bot@*",)  # alone; narrowed by the maintainer
HUMAN_FALLBACK_PAIRS = (("Carter", "state@carter.invalid"),)  # only together
LINK_CACHE_REL = ".carter/run/coauthor-link.json"
LINK_CACHE_TTL_S = 7 * 24 * 3600
LINK_STATES = ("noreply", "verified")
# K3: the new code. K10: the flag.
ERRORS_NEW_2C = ("E-HUMAN-IDENTITY",)
ADD_ROLE_CHOICES = ("co-author", "author")


@pytest.mark.parametrize("path", sorted(MODULES_2C), ids=str)
def test_2c_module_paths_exist_once_their_step_has_run(path: str) -> None:
    if (REPO / path).exists():
        return
    if os.environ.get("CARTER_NAMES_STRICT") == "1":
        pytest.fail(f"{path} ({MODULES_2C[path]}) is frozen but missing")
    pytest.skip(f"{path} arrives in {MODULES_2C[path]}")


def test_k5_the_role_b_signing_env_keys_and_the_role_a_keys_stay() -> None:
    payload = pytest.importorskip("carter.identity.payload")
    assert payload.SIGNING_ENV_KEYS_B == SIGNING_ENV_KEYS_B
    assert payload.SIGNING_ENV_KEYS == SIGNING_ENV_KEYS
    assert set(SIGNING_ENV_KEYS) < set(SIGNING_ENV_KEYS_B)
    vectors = json.loads((REPO / "tests/data/plugin_vectors.json").read_text())
    assert tuple(vectors["signing"]["env_keys_role_b"]) == SIGNING_ENV_KEYS_B


def test_k3_the_reasons_replace_role_b_not_built() -> None:
    payload = pytest.importorskip("carter.identity.payload")
    assert "role-b-not-built" not in payload.REASONS
    assert payload.REASONS[-2] == "human-identity-invalid"  # CI-E appended review-mode after it


def test_k2_the_human_identity_problems_and_fallbacks() -> None:
    from carter.identity.rules import human_identity_rules

    coauthor = pytest.importorskip("carter.identity.coauthor")
    assert coauthor.PROBLEMS == HUMAN_PROBLEMS
    rules = human_identity_rules()
    assert tuple(rules["fallback_emails"]) == HUMAN_FALLBACK_EMAILS
    assert tuple(tuple(p) for p in rules["fallback_pairs"]) == HUMAN_FALLBACK_PAIRS
    vectors = json.loads((REPO / "tests/data/human_identity_vectors.json").read_text())
    assert {c["problem"] for c in vectors["cases"]} - {""} == set(HUMAN_PROBLEMS)


def test_k7_the_link_cache_name_ttl_and_states() -> None:
    coauthor = pytest.importorskip("carter.identity.coauthor")
    if not hasattr(coauthor, "LINK_CACHE_REL"):
        pytest.skip("the link cache arrives in step 6")
    assert coauthor.LINK_CACHE_REL == LINK_CACHE_REL
    assert coauthor.LINK_CACHE_TTL_S == LINK_CACHE_TTL_S
    assert coauthor.LINK_STATES == LINK_STATES


def test_k3_the_2c_error_code_exists_with_the_2c_tag() -> None:
    reg = registry()
    for code in ERRORS_NEW_2C:
        assert reg[code].slice == "2c" and reg[code].message and "\n" not in reg[code].message, code
        assert "no downgrade" in reg[code].message
    assert reg["E-ROLE-B-TIER"].slice == "1"  # reused, text unchanged


def test_k10_identity_add_has_the_role_option() -> None:
    cli = pytest.importorskip("carter.identity_cli")
    add = cli.identity.commands["add"]
    role = next((o for o in add.params if o.opts[0] == "--role"), None)
    if role is None:
        pytest.skip("--role arrives in step 8")
    assert tuple(role.type.choices) == ADD_ROLE_CHOICES


def test_k13_the_current_slice_is_2c_once_step_11_has_run() -> None:
    from carter.identity.rules import CURRENT_SLICE

    if CURRENT_SLICE not in ("2c", "B", "CI-E"):
        pytest.skip("CURRENT_SLICE moves to 2c in step 11")
    assert "E-HUMAN-IDENTITY" in registry()


# ---------------------------------------------------------------------------------------------
# Slice B (plan 007 step 5, freeze B1-B20), frozen before dependent code. Same rules as above.
# ---------------------------------------------------------------------------------------------

MODULES_B = (
    "carter/broker/__init__.py", "carter/broker/env.py", "carter/broker/argv.py",
    "carter/broker/checks.py", "carter/broker/plan.py", "carter/broker/execute.py",
    "carter/broker/pr.py", "carter/broker/counter.py", "carter/broker/audit.py",
    "carter/broker_cli.py", "carter/plugin/broker.ts",
    "tests/data/b_hostile_argv.json", "tests/data/ssh_g/index.json",
)  # fmt: skip
BROKER_ENTRY = ("-I", "-m", "carter.broker_cli")  # B2 / T6: the only entry
BROKER_SUBCOMMANDS = ("push", "pr", "record")
BROKER_MODES = ("plan", "execute")  # --plan / --exec
RECORD_OUTCOMES = ("rejected", "timeout", "aborted", "corrected", "dwell")
BROKER_EXIT_CODES = {"ok": 0, "refused": 1, "usage": 2}
DEVOPS_AGENT = "carter-devops"  # B10 / T9
# B3 / T5: Python judges the dwell; the floor is 500 ms, configurable upward only.
DWELL = {"default": 500, "floor": 500, "cap": 10000, "timeout_ms": 120000}
# B5
REJECTIONS_MAX = 3
COUNTER_FILE = "b-rejections.json"
# B15
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
# B4: the plan JSON (common keys, then per verb)
PLAN_COMMON_KEYS = ("approval", "ask", "audit", "branch", "pinned_sha", "repo", "verb")
PLAN_PUSH_KEYS = ("base_label", "commits", "count", "new", "new_branch", "old", "sensitive")
PLAN_PR_KEYS = ("base", "body_lines", "body_preview", "draft", "head_sha", "title")
APPROVAL_KEYS = ("min_dwell_ms", "timeout_ms")
ASK_KEYS = ("metadata", "resources")
# B9: isolation.json schema 2
ISOLATION_B_KEYS = ("b_enabled", "b_caller", "broker_args", "b_git", "b_gh")
CONSENT_REV_PLUGIN, CONSENT_REV_BROKER = 2, 3
HEADLESS_PROFILE = "opencode-headless.json"
BROKER_CONFIG_KEYS = ("min_dwell_ms",)  # no home key (maestro decision, plan 007)
# B16 (E-B-HEADLESS is raised by OpenCode; E-B-REPOCFG, E-B-UNSIGNED and E-SECRET-SCAN are older)
ERRORS_B = (
    "E-B-CALLER", "E-B-DWELL", "E-B-TIMEOUT", "E-B-HEADLESS", "E-B-POLLUTED", "E-B-NOAGENT",
    "E-B-HTTPS", "E-B-MOVED", "E-B-DEFAULT", "E-B-ARGS", "E-B-REJECTED",
)  # fmt: skip
# B19
BROKER_TS_MAX_LINES, INDEX_TS_MAX_LINES = 200, 80
# B11: where git and gh may be found at install (never PATH at runtime)
TOOL_DIRS = ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin")


@pytest.mark.parametrize("path", MODULES_B)
def test_b_module_paths_exist(path: str) -> None:
    assert (REPO / path).exists(), f"{path} is frozen but missing"


def test_b1_b2_the_entry_the_subcommands_and_the_exit_codes() -> None:
    cli = pytest.importorskip("carter.broker_cli")
    assert tuple(cli.OUTCOMES) == RECORD_OUTCOMES
    assert tuple(BROKER_EXIT_CODES.values()) == (cli.EXIT_OK, cli.EXIT_REFUSED, cli.EXIT_USAGE)
    from carter.identity import rules

    assert tuple(rules.plugin_defaults()["broker_args"]) == BROKER_ENTRY
    sub = cli.parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert tuple(sub) == BROKER_SUBCOMMANDS
    for verb in ("push", "pr"):
        flags = {o for a in sub[verb]._actions for o in a.option_strings}
        assert {"--plan", "--exec", "--pinned-sha", "--asked-at", "--answered-at"} <= flags
        assert not {"--remote", "--ref", "--url", "--refspec", "--force", "--branch"} & flags


def test_b3_the_dwell_and_timeout_constants() -> None:
    from carter.broker import plan

    assert (
        DWELL["default"], DWELL["floor"], DWELL["cap"], DWELL["timeout_ms"]
    ) == (plan.DWELL_DEFAULT_MS, plan.DWELL_FLOOR_MS, plan.DWELL_CAP_MS, plan.TIMEOUT_MS)  # fmt: skip
    assert plan.DWELL_FLOOR_MS >= 500  # T5: the 150 ms floor of D49 was too low (spike B3)
    from carter.identity.schema import Broker

    assert Broker().min_dwell_ms == DWELL["default"]


def test_b5_the_counter_file_and_limit() -> None:
    from carter.broker import counter

    assert (counter.MAX_REJECTIONS, counter.FILE) == (REJECTIONS_MAX, COUNTER_FILE)


def test_b10_the_only_caller() -> None:
    import carter.broker as broker
    from carter.identity import rules

    assert broker.DEVOPS_AGENT == DEVOPS_AGENT == rules.plugin_defaults()["b_caller"]
    assert broker.VERBS == ("push", "pr")  # widening B needs a new ADR


def test_b15_the_audit_store() -> None:
    from carter.broker import audit

    assert tuple(audit.FIELDS) == AUDIT_FIELDS and tuple(audit.DECISIONS) == AUDIT_DECISIONS
    assert (audit.B_LOG, audit.OPS_LOG) == AUDIT_FILES
    assert (audit.ROTATE_BYTES, audit.ROTATE_KEEP) == (AUDIT_ROTATE_BYTES, AUDIT_ROTATE_KEEP)
    assert audit.audit_dir(Path("/c")) == Path("/c").joinpath(*AUDIT_DIR_REL)


def test_b4_the_plan_json_keys(tmp_path: Path) -> None:
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


def test_b9_the_isolation_broker_keys_and_the_consent_revisions() -> None:
    from carter.guard import consent

    assert set(ISOLATION_B_KEYS) <= set(ISOLATION_PLUGIN_KEYS)
    assert (consent.PLUGIN_REV, consent.BROKER_REV) == (CONSENT_REV_PLUGIN, CONSENT_REV_BROKER)
    assert {g.id: g.rev for g in policyset.consent_groups()}["g2"] == CONSENT_REV_BROKER
    g2 = next(g for g in policyset.consent_groups() if g.id == "g2")
    assert "not a security boundary" in " ".join(g2.explain)  # residual 6, B9


def test_b8_the_headless_profile_name_and_content() -> None:
    from carter.guard import plugin
    from carter.install import paths

    assert paths.headless_profile_path(None).name == HEADLESS_PROFILE
    doc = json.loads(plugin.render_headless())
    assert list(doc) == ["agents"] and list(doc["agents"]) == [DEVOPS_AGENT]
    assert "policies" not in doc  # a global tool.use policy never matches a plugin tool (A6)
    assert {r["action"] for r in doc["agents"][DEVOPS_AGENT]["permissions"]} == set(
        AGENT_PERMISSION_DENIES
    )


def test_b11_the_tool_directories_are_fixed() -> None:
    from carter.guard import plugin

    assert tuple(plugin.TOOL_DIRS) == TOOL_DIRS


def test_b3_the_broker_config_table() -> None:
    from carter.identity.schema import schema_names

    assert schema_names()["broker"] == BROKER_CONFIG_KEYS


def test_b16_the_b_error_codes_exist_with_the_b_tag() -> None:
    reg = registry()
    for code in ERRORS_B:
        assert reg[code].slice == "B" and reg[code].message and "\n" not in reg[code].message, code
    for older in ("E-B-REPOCFG", "E-B-UNSIGNED"):
        assert reg[older].slice == "1G"


def test_b18_the_current_slice_is_b_or_later() -> None:
    from carter.identity.rules import CURRENT_SLICE

    assert CURRENT_SLICE in ("B", "CI-E")  # plan 008 moved it to CI-E


def test_b19_the_ts_budgets() -> None:
    assert len((REPO / "carter/plugin/broker.ts").read_text().splitlines()) <= BROKER_TS_MAX_LINES
    assert len((REPO / "carter/plugin/index.ts").read_text().splitlines()) <= INDEX_TS_MAX_LINES


# ---------------------------------------------------------------------------------------------
# Slice CI-E (plan 008 step 3, freeze C1-C14), frozen before dependent code. Same rules as above.
# ---------------------------------------------------------------------------------------------

MODULES_CIE = (
    "carter/ci/__init__.py", "carter/ci/template.py", "carter/ci/check.py",
    "carter/ci/review.py", "carter/ci/install.py", "carter/ci_cli.py",
    "carter/identity/mode.py", "templates/ci/carter-review.yml.tmpl",
    "tests/data/workflows/good-minimal.yml",
)  # fmt: skip
CIE_WORKFLOW_REL = ".github/workflows/carter-review.yml"
CIE_ENVIRONMENT, CIE_SECRET = "carter-review", "LLM_API_KEY"  # C5
CIE_COMMANDS = ("check", "install", "review")  # C1, C12
CIE_INSTALL_OPTIONS = ("--comment", "--dry-run", "--force")
CIE_MODES = ("auto", "interactive", "review")  # C3
CIE_UNBUILT = ("commit", "scheduled", "ci", "c", "d")  # CI contexts C and D (RFC §4.1)
CIE_MODE_ENV = "CARTER_IDENTITY_MODE"
CIE_ERROR = "E-CI-REVIEW"  # C4
CIE_REASON = "review-mode"  # the identity entry's reason
CIE_RULES = tuple(f"CI{n:03d}" for n in range(14))  # C9: CI000-CI013
CIE_DRIVER_ENV = (
    "LLM_API_KEY", "CARTER_CI_BASE_SHA", "CARTER_CI_KEY_ENV", "CARTER_CI_MODEL",
    "CARTER_CI_COMMENT_FILE", "GITHUB_STEP_SUMMARY", "GITHUB_EVENT_PATH",
)  # fmt: skip
CIE_AGENT = "carter-ci-reviewer"  # C6
CIE_READ_ONLY = ("read", "glob", "grep")  # C7
CIE_COMMENT_JOB = "comment"  # C8
CIE_GATE_ITEM = "carter ci install"  # added to the human-only Carter verbs


@pytest.mark.parametrize("path", MODULES_CIE)
def test_cie_module_paths_exist(path: str) -> None:
    assert (REPO / path).exists(), f"{path} is frozen but missing"


def test_cie_c1_the_installer_shape() -> None:
    click = pytest.importorskip("click")
    from carter.ci_cli import ci

    assert isinstance(ci, click.Group) and tuple(sorted(ci.commands)) == CIE_COMMANDS
    options = {o for p in ci.commands["install"].params for o in getattr(p, "opts", ())}
    assert set(CIE_INSTALL_OPTIONS) <= options
    import carter.ci as pkg

    assert pkg.WORKFLOW_REL == CIE_WORKFLOW_REL


def test_cie_c3_the_modes_and_their_precedence() -> None:
    from carter.identity import mode

    assert mode.MODES == CIE_MODES and mode.ENV_MODE == CIE_MODE_ENV
    assert tuple(mode.UNBUILT) == CIE_UNBUILT
    assert mode.resolve_mode("", {"CI": "true"}).mode == "review"  # auto in CI
    assert mode.resolve_mode("interactive", {}).mode == "interactive"
    assert mode.resolve_mode("review", {CIE_MODE_ENV: "interactive"}).source == "env"


def test_cie_c4_the_refusal_code_and_the_reason() -> None:
    from carter.identity import payload

    entry = registry()[CIE_ERROR]
    assert entry.slice == "CI-E" and "\n" not in entry.message and "review run" in entry.message
    assert CIE_REASON in payload.REASONS


def test_cie_c5_the_secret_and_the_environment() -> None:
    import carter.ci as pkg

    assert (pkg.ENVIRONMENT, pkg.SECRET) == (CIE_ENVIRONMENT, CIE_SECRET)


def test_cie_c6_c7_the_review_agent_can_only_read() -> None:
    from carter.ci import review

    assert review.AGENT == CIE_AGENT and tuple(review.ALLOWED_ACTIONS) == CIE_READ_ONLY
    assert tuple(review.build_profile()["agents"]) == (CIE_AGENT,)
    for name in CIE_DRIVER_ENV:
        assert name in (REPO / "carter/ci/review.py").read_text() or name == "LLM_API_KEY"


def test_cie_c8_c9_the_comment_job_and_the_rule_ids() -> None:
    import carter.ci as pkg
    from carter.ci import check

    assert pkg.COMMENT_JOB == CIE_COMMENT_JOB
    for rule in CIE_RULES:
        assert rule in (check.__doc__ or ""), rule


def test_cie_c10_the_current_slice_is_ci_e() -> None:
    from carter.identity.rules import CURRENT_SLICE

    assert CURRENT_SLICE == "CI-E"


def test_cie_the_installer_is_a_human_only_carter_verb() -> None:
    data = json.loads((REPO / "carter/identity/g2_rules.json").read_text())
    (cls,) = [c for c in data["forbidden"] if c["id"] == "human-only-carter"]
    assert CIE_GATE_ITEM in cls["items"]
