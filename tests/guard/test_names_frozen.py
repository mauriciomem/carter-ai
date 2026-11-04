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
LIVE_GROUPS = ("g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit", "repo_hooks")

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


def test_live_groups_are_all_but_alias() -> None:
    assert tuple(g.id for g in policyset.consent_groups() if g.live) == LIVE_GROUPS


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

# G10: consent group revisions at 2a (g2 moves to 2 with the plugin).
CONSENT_REVS = {
    "g2": 2,
    "hooks": 1,
    "sudo-docker": 1,
    "read-edit-denies": 1,
    "config-edit": 1,
    "alias": 1,
    "repo_hooks": 1,
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


def test_consent_groups_carry_their_revision() -> None:
    assert {g.id: g.rev for g in policyset.consent_groups()} == CONSENT_REVS


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
    assert tuple(vectors["tier"]["reasons"]) == TIER_REASONS
    assert set(vectors) >= {"ad1", "pollution", "count", "marker", "isolation", "tier", "status"}
