"""Agent `permissions:` derive from the resolved access level.

The reference for the `guarded` level is the renderer as it was before levels existed
(`_legacy_rules`, copied from it): `guarded` must render the same, except the rows listed in
`_intended_changes`. `strict` is the default; every other test pins one capability to its rules.
"""

from __future__ import annotations

import pytest
import yaml

from carter.access import UserAccess
from carter.config import (
    _ALWAYS_DENY,
    _BASH_COMMANDS,
    _DISCOVERY_ACTIONS,
    _OPENCODE_GATE,
    AGENT_ALLOWLIST,
    PRIMARY_ROLE,
    RISK_TAXONOMY,
    _broker_denies,
    _rule,
    generate_default_config,
    permission_rules,
    with_guard_rules,
    with_user_access,
)
from carter.identity.policyset import agent_mcp_denies

ROLES = tuple(AGENT_ALLOWLIST)
LOCAL_WRITE = ("pm", "narrator", "engineer", "security", "devops")
# What G2 appends when it is installed: a `gh *` deny, then the `gh` allows.
G2 = [
    _rule("shell", "git push *", "deny"),
    _rule("shell", "gh *", "deny"),
    _rule("shell", "gh pr view *", "allow"),
    _rule("shell", "gh pr create *", "allow"),
    _rule("shell", "gh pr comment *", "allow"),
]
ISSUE = ("gh issue create *", "gh issue comment *")
DESTRUCTIVE = ("rm -rf *", "git reset --hard *", "git push --force *")


def _config(level=None, /, *, guard_rules=(), **access):
    """A default config; ``level`` and ``access`` make the human's ``[access]`` (none if unset)."""
    table = ({"level": level} if level else {}) | access
    config = with_user_access(generate_default_config(), UserAccess(table=table or None))
    return with_guard_rules(config, list(guard_rules))


def _verdict(rules, resource):
    """What OpenCode does with ``resource``: the effect of the last row that names it."""
    return [r["effect"] for r in rules if r["resource"] == resource][-1]


def _legacy_rules(role, guard_rules=()):
    """The renderer before access levels, at the `guarded` level (the old default)."""
    allowed = [cat for cat, on in sorted(AGENT_ALLOWLIST.get(role, {}).items()) if on]
    gates = {cat: RISK_TAXONOMY[cat]["guarded"] for cat in allowed}
    writes = "local-write" in allowed
    rules = [_rule("*", "*", "ask")]
    rules += [_rule(action, "*", "allow") for action in _DISCOVERY_ACTIONS]
    rules += [
        _rule("read", "*.env", "ask"),
        _rule("read", "*.env.*", "ask"),
        _rule("read", "*.env.example", "allow"),
        _rule("external_directory", "~/.carter/*", "allow"),
        _rule("read", "~/.carter/*", "allow"),
    ]
    if writes:
        rules.append(_rule("edit", "~/.carter/memories/*", "allow"))
    rules.append(_rule("subagent", "*", "deny"))
    if role == PRIMARY_ROLE:
        rules.append(_rule("subagent", "carter-*", "allow"))
    rules += _broker_denies(role)
    local = "allow" if writes else "ask"
    rules += [_rule(action, "*", local) for action in ("edit", "shell", "webfetch")]
    for cat, commands in _BASH_COMMANDS.items():
        if cat in _ALWAYS_DENY:
            effect = "deny"
        else:
            effect = _OPENCODE_GATE[gates[cat]] if cat in allowed else "deny"
        rules += [_rule("shell", cmd, effect) for cmd in commands]
    return rules + [dict(r) for r in guard_rules]


def _intended_changes(legacy, role, issue="ask"):
    """The only two differences of `guarded` from the old render, by design:

    * `destructive` follows the level for every local-write role (it was denied to all but
      devops): ``rm -rf``, ``reset --hard`` and ``push --force`` ask;
    * the two issue verbs left the always-denied list; `issue_write` owns them, after G2's rules.
    """
    out = []
    for rule in legacy:
        if rule["resource"] in ISSUE:
            continue
        if rule["resource"] in DESTRUCTIVE and role in LOCAL_WRITE:
            rule = {**rule, "effect": "ask"}
        out.append(rule)
    return out + [_rule("shell", cmd, issue) for cmd in ISSUE]


class TestGuardedRendersAsToday:
    @pytest.mark.parametrize("guard", [(), G2], ids=["no-g2", "g2"])
    @pytest.mark.parametrize("role", ROLES)
    def test_guarded_equals_the_old_render_but_for_the_intended_rows(self, role, guard):
        got = permission_rules(_config("guarded", guard_rules=guard), role)
        assert got == _intended_changes(_legacy_rules(role, guard), role)

    @pytest.mark.parametrize("role", ROLES)
    def test_relaxed_is_guarded_plus_issue_verbs_allowed(self, role):
        guarded = permission_rules(_config("guarded"), role)
        relaxed = permission_rules(_config("relaxed"), role)
        assert relaxed == [*guarded[:-2], *(_rule("shell", c, "allow") for c in ISSUE)]


class TestStrictIsTheDefault:
    @pytest.mark.parametrize("role", ROLES)
    def test_no_access_table_renders_strict(self, role):
        assert permission_rules(_config(), role) == permission_rules(_config("strict"), role)

    @pytest.mark.parametrize("role", ROLES)
    def test_strict_denies_destructive_infra_and_issues_and_asks_for_prs(self, role):
        rules = permission_rules(_config(), role)
        for cmd in (*DESTRUCTIVE, "terraform apply *", "kubectl apply *", "vault read *", *ISSUE):
            assert _verdict(rules, cmd) == "deny", (role, cmd)
        for cmd in ("gh pr create *", "gh pr edit *", "gh pr comment *"):
            assert _verdict(rules, cmd) == "ask", (role, cmd)

    @pytest.mark.parametrize("role", LOCAL_WRITE)
    def test_strict_still_lets_writers_edit_and_run(self, role):
        rules = permission_rules(_config(), role)
        assert _rule("edit", "*", "allow") in rules and _rule("shell", "*", "allow") in rules

    @pytest.mark.parametrize("role", ROLES)
    def test_strict_changes_nothing_else_for_a_role_that_had_nothing(self, role):
        strict = permission_rules(_config(), role)
        guarded = permission_rules(_config("guarded"), role)
        assert [r for r in strict if r["action"] != "shell"] == [
            r for r in guarded if r["action"] != "shell"
        ]


class TestCapabilities:
    def test_pr_write_ask_and_denied_rows(self):
        rules = permission_rules(_config("guarded", pr_write="ask"), "engineer")
        assert _verdict(rules, "gh pr create *") == _verdict(rules, "gh pr comment *") == "ask"
        rules = permission_rules(_config("guarded", pr_write="denied"), "engineer")
        assert _verdict(rules, "gh pr create *") == "deny"

    def test_pr_write_allowed_adds_no_row(self):
        rules = permission_rules(_config("relaxed"), "engineer")
        assert not [r for r in rules if r["resource"].startswith("gh pr create")]

    def test_issue_write_follows_the_level_after_g2_denies_gh(self):
        for level, expected in (("strict", "deny"), ("guarded", "ask"), ("relaxed", "allow")):
            rules = permission_rules(_config(level, guard_rules=G2), "engineer")
            assert rules.index(_rule("shell", ISSUE[0], expected)) > rules.index(G2[1])
            assert _verdict(rules, ISSUE[0]) == _verdict(rules, ISSUE[1]) == expected

    def test_a_row_after_g2_never_opens_a_g2_deny_but_issue_verbs(self):
        for level in LEVELS_WITH_G2:
            rules = permission_rules(_config(level, guard_rules=G2), "devops")
            after = rules[len(rules) - rules[::-1].index(G2[-1]) :]
            assert all(r["effect"] != "allow" or r["resource"] in ISSUE for r in after)

    @pytest.mark.parametrize(
        ("access", "role", "expected"),
        [
            ({"workspace_edit": "ask"}, "engineer", ("edit", "*", "ask")),
            ({"workspace_edit": "denied"}, "engineer", ("edit", "*", "deny")),
            ({"run_commands": "ask"}, "devops", ("shell", "*", "ask")),
            ({"run_commands": "denied"}, "pm", ("shell", "*", "deny")),
            ({"git_commit": "ask"}, "engineer", ("shell", "git commit *", "ask")),
            ({"git_commit": "denied"}, "engineer", ("shell", "git commit *", "deny")),
            ({"github_read": "ask"}, "engineer", ("shell", "gh pr view *", "ask")),
            ({"github_read": "denied"}, "engineer", ("shell", "gh run list *", "deny")),
            ({"github_read": "denied"}, "engineer", ("carter_github_*", "*", "deny")),
            ({"destructive": "denied"}, "engineer", ("shell", "rm -rf *", "deny")),
            ({"infra_apply": "denied"}, "devops", ("shell", "terraform apply *", "deny")),
            ({"infra_apply": "denied"}, "devops", ("shell", "vault read *", "deny")),
        ],
    )
    def test_override_reaches_the_rules(self, access, role, expected):
        rules = permission_rules(_config("guarded", **access), role)
        assert _rule(*expected) in rules

    @pytest.mark.parametrize("role", [r for r in ROLES if r not in LOCAL_WRITE])
    def test_a_read_only_role_never_gets_looser_than_ask(self, role):
        rules = permission_rules(_config("relaxed"), role)
        assert _rule("edit", "*", "ask") in rules and _rule("shell", "*", "ask") in rules
        assert _verdict(rules, "rm -rf *") == "deny"

    def test_infra_apply_reaches_devops_only(self):
        for role in ROLES:
            expected = "ask" if role == "devops" else "deny"
            rules = permission_rules(_config("guarded"), role)
            assert _verdict(rules, "terraform apply *") == expected, role

    def test_a_learner_keeps_its_github_mcp_deny(self):
        action, roles = agent_mcp_denies()
        for role in roles:
            rules = permission_rules(_config("guarded", github_read="ask"), role)
            assert [r["effect"] for r in rules if r["action"] == action] == ["deny"]

    def test_opencode_config_has_no_rule_of_its_own(self):
        """It is fixed `denied` and opened only by the per-workspace opt-out, which G2 renders."""
        assert permission_rules(_config("guarded"), "engineer") == permission_rules(
            _config("relaxed", issue_write="ask"), "engineer"
        )


LEVELS_WITH_G2 = ("strict", "guarded", "relaxed")


class TestHardenOnly:
    def test_a_workspace_value_hardens(self):
        config = _config("guarded") | {"access": {"pr_write": "denied"}}
        assert _verdict(permission_rules(config, "engineer"), "gh pr create *") == "deny"

    def test_a_looser_workspace_cannot_loosen(self):
        config = _config("strict") | {"access": {"level": "relaxed", "pr_write": "allowed"}}
        assert permission_rules(config, "engineer") == permission_rules(
            _config("strict"), "engineer"
        )

    def test_the_policy_level_alias_hardens_but_never_loosens(self):
        guarded = _config("guarded") | {"policy": {"level": "strict"}}
        assert permission_rules(guarded, "devops") == permission_rules(_config("strict"), "devops")
        strict = _config() | {"policy": {"level": "relaxed"}}
        assert permission_rules(strict, "devops") == permission_rules(_config("strict"), "devops")

    def test_policy_overrides_still_tighten_on_top(self):
        config = _config("guarded")
        config["policy"] = {"overrides": {"dangerous": "deny"}}
        rules = permission_rules(config, "devops")
        assert _verdict(rules, "terraform apply *") == _verdict(rules, "rm -rf *") == "deny"

    def test_a_switched_off_category_denies_the_infra_rows_but_not_the_others(self):
        config = _config("guarded")
        config["policy"] = {"allowlist": {"devops": {"dangerous": False}}}
        rules = permission_rules(config, "devops")
        assert _verdict(rules, "terraform apply *") == "deny"
        assert _verdict(rules, "rm -rf *") == "ask"  # `destructive` is every writer's (D6)


class TestFailClosed:
    @pytest.mark.parametrize(
        "access",
        [{"gitcommit": "ask"}, {"gh_api": "allowed"}, {"destructive": "allowed"}, {"level": "x"}],
    )
    @pytest.mark.parametrize("role", ROLES)
    def test_any_access_error_renders_strict(self, role, access):
        broken = _config("relaxed", **access)
        assert permission_rules(broken, role) == permission_rules(_config("strict"), role)

    @pytest.mark.parametrize("role", ROLES)
    def test_an_unreadable_config_renders_strict(self, role):
        config = with_user_access(generate_default_config(), UserAccess(error="bad"))
        assert permission_rules(config, role) == permission_rules(_config("strict"), role)


class TestEveryReaderUsesOneResolver:
    def _frontmatter(self, text):
        return yaml.safe_load(text.split("---", 2)[1])

    @pytest.mark.parametrize("level", ["strict", "guarded", "relaxed"])
    def test_global_and_workspace_agents_carry_the_same_permissions(self, level, tmp_path):
        from carter.install.components import _render_opencode_agents
        from carter.scaffold import create_env, render_agents

        carter_dir = tmp_path / "carter"
        carter_dir.mkdir()
        (carter_dir / "config.toml").write_text(f'[access]\nlevel = "{level}"\n')
        user = UserAccess(table={"level": level})
        workspace = generate_default_config(workspace_name="w", mode="single")
        local = render_agents(workspace, create_env(), [], user)
        global_ = _render_opencode_agents(tmp_path)
        for role in AGENT_ALLOWLIST:
            have = self._frontmatter(global_[f"carter-{role}.md"])["permissions"]
            want = self._frontmatter(local[f"carter-{role}-local.md"])["permissions"]
            assert have == want == permission_rules(_config(level), role), role

    def test_lint_and_render_use_the_same_function(self):
        from carter.config import resolve_model
        from carter.scaffold import lint_policy

        config = generate_default_config(workspace_name="w", mode="single")
        installed = {
            "engineer": {
                "model": resolve_model(config, "engineer"),
                "permissions": permission_rules(_config("guarded"), "engineer"),
            }
        }
        guarded = UserAccess(table={"level": "guarded"})
        assert lint_policy(config, installed, [], guarded) == []
        drift = lint_policy(config, installed, [], UserAccess())  # the default is strict
        assert drift and "drifted" in drift[0]
