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
LIVE_GROUPS = ("g2", "sudo-docker", "read-edit-denies", "config-edit")

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


def test_live_groups_are_the_four_with_content() -> None:
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
