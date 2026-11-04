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
    assert set(defaults) == {*PLUGIN_DEFAULTS, "gh_token_dummy", "status_dir"}


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
    assert doc["schema_version"] == 1
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
H2_SIGNING_DEFAULTS = {"ttl": "8h", "ssh_bin_dir": "/usr/bin"}
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
)

# H5: the keys of Carter's gitconfig, and the fragment name rule (step 13).
CARTER_GIT_KEYS = ("carter.tier", "carter.llmEmail", "carter.llmFingerprint")

# H8/H9: the shim's allow-list and the minimum versions. The data lives in g2_rules.json.
SHIM_Y_OPS = ("verify", "find-principals", "check-novalidate")
MIN_GIT_SIGNING = (2, 40)
MIN_OPENSSH = (8, 4)

# H10/H12: the unlock and lock commands (the rest of the identity group arrives in 13-17).
IDENTITY_SUBCOMMANDS = ("add", "show", "verify", "unlock", "lock", "remove", "env")
UNLOCK_OPTIONS = ("--allow-no-passphrase", "--extend", "--ttl")
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

# H15: consent revisions after 2b (step 19). `g2` stays 2: isolation.json is unchanged.
CONSENT_REVS_2B = {
    "g2": 2,
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
    "E-UNLOCK-NOPASS",
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

    assert CURRENT_SLICE == "2c"  # moved by plan 006 step 11 (K13)


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
    assert payload.REASONS[-1] == "human-identity-invalid"


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

    if CURRENT_SLICE != "2c":
        pytest.skip("CURRENT_SLICE moves to 2c in step 11")
    assert "E-HUMAN-IDENTITY" in registry()
