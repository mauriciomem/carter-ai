"""The access resolver: presets, merge, validation messages, fail-closed."""

from __future__ import annotations

import pytest

from carter.access import (
    CAPABILITY_IDS,
    FLOOR_IDS,
    GROUP_FLOORS,
    LEVELS,
    missing_group_lines,
    missing_groups_summary,
    resolve,
    warnings,
)
from test_access_schema import RFC_TABLE

MAX_LINE = 80
STRICT = {cap_id: row[0] for cap_id, row in RFC_TABLE.items()}
FALLBACK = "! access config invalid: using strict"


def _lines_ok(result):
    assert all(len(line) <= MAX_LINE for line in result.notes), result.notes


class TestPresets:
    @pytest.mark.parametrize("level", LEVELS)
    @pytest.mark.parametrize("cap_id", RFC_TABLE)
    def test_level_gives_the_rfc_table(self, level, cap_id):
        result = resolve({"level": level})
        assert result.values[cap_id] == RFC_TABLE[cap_id][LEVELS.index(level)]
        assert result.sources[cap_id] == "preset"
        assert result.notes == ()

    def test_absent_access_is_strict(self):
        result = resolve(None)
        assert result.values == STRICT
        assert (result.level, result.level_source, result.notes) == ("strict", "default", ())

    def test_table_without_level_is_strict(self):
        assert resolve({}).values == STRICT

    def test_every_id_is_resolved(self):
        assert tuple(resolve(None).values) == CAPABILITY_IDS


class TestOverrides:
    def test_override_replaces_the_preset_in_either_direction(self):
        result = resolve({"level": "guarded", "pr_write": "ask", "git_commit": "denied"})
        assert (result.values["pr_write"], result.sources["pr_write"]) == ("ask", "override")
        assert (result.values["git_commit"], result.sources["git_commit"]) == ("denied", "override")
        assert result.values["issue_write"] == "ask"
        assert result.sources["issue_write"] == "preset"

    def test_override_up_to_the_max_is_accepted(self):
        result = resolve({"destructive": "ask", "infra_apply": "ask", "opencode_config": "denied"})
        assert result.notes == ()
        assert result.values["destructive"] == "ask"

    def test_the_user_access_table_with_only_a_level_is_not_touched(self):
        """`[access] level = "guarded"` in the real config.toml is the minimal valid table."""
        assert resolve({"level": "guarded"}).level == "guarded"


class TestUserErrors:
    """Every error: the exact line, then the fallback, and strict everywhere."""

    @pytest.mark.parametrize(
        ("table", "message"),
        [
            ({"gitcommit": "ask"}, "config.toml [access]: unknown key 'gitcommit'"),
            ({"gh_api": "allowed"}, "config.toml [access]: gh_api is fixed at never"),
            ({"destructive": "allowed"}, "config.toml [access]: destructive max is ask"),
            ({"infra_apply": "allowed"}, "config.toml [access]: infra_apply max is ask"),
            (
                {"opencode_config": "ask"},
                "config.toml [access]: opencode_config max is denied",
            ),
            (
                {"pr_write": "yes"},
                "config.toml [access]: pr_write must be allowed/ask/denied",
            ),
            (
                {"pr_write": 1},
                "config.toml [access]: pr_write must be allowed/ask/denied",
            ),
            (
                {"level": "open"},
                "config.toml [access]: level must be strict/guarded/relaxed",
            ),
            ({"level": ["strict"]}, "config.toml [access]: level must be strict/guarded/relaxed"),
        ],
    )
    def test_message_then_fallback(self, table, message):
        result = resolve({"level": "relaxed", **table})
        assert result.notes == (message, FALLBACK)
        assert result.values == STRICT
        assert result.level_source == "fallback"
        _lines_ok(result)

    @pytest.mark.parametrize("floor_id", FLOOR_IDS)
    def test_every_floor_id_is_refused(self, floor_id):
        result = resolve({floor_id: "allowed"})
        assert result.notes[0] == f"config.toml [access]: {floor_id} is fixed at never"
        assert result.values == STRICT

    def test_a_table_that_is_not_a_table_fails_closed(self):
        result = resolve("guarded")
        assert result.notes == ("config.toml [access]: must be a table", FALLBACK)
        assert result.values == STRICT

    def test_all_errors_are_reported_before_one_fallback(self):
        result = resolve({"level": "x", "gitcommit": "ask"})
        assert len(result.notes) == 3
        assert result.notes[-1] == FALLBACK

    def test_echoed_key_is_escaped_and_cut_at_32(self):
        result = resolve({"a\x1b[31m" + "z" * 100: "ask"})
        line = result.notes[0]
        assert "\x1b" not in line
        assert "a\\x1b[31m" in line
        assert len(line) <= MAX_LINE
        assert "z" * 40 not in line

    def test_non_string_key_does_not_crash(self):
        assert resolve({1: "ask"}).values == STRICT


class TestWorkspace:
    def test_absent_workspace_changes_nothing(self):
        assert resolve({"level": "guarded"}, workspace=None).values["pr_write"] == "allowed"

    def test_a_stricter_workspace_wins(self):
        result = resolve({"level": "guarded"}, workspace={"pr_write": "denied"})
        assert (result.values["pr_write"], result.sources["pr_write"]) == ("denied", "workspace")
        assert result.notes == ()

    def test_a_stricter_workspace_level_hardens_every_row(self):
        result = resolve({"level": "relaxed"}, workspace={"level": "strict"})
        assert result.values == STRICT
        assert result.sources["pr_write"] == "workspace"
        assert result.sources["workspace_edit"] == "preset"  # no change, no credit

    def test_a_looser_row_is_ignored_with_one_line(self):
        result = resolve({"level": "strict"}, workspace={"pr_write": "allowed"})
        assert result.values == STRICT
        assert result.notes == ("! carter.yaml access.pr_write ignored: can only harden",)

    def test_a_looser_level_is_ignored_with_one_line(self):
        result = resolve({"level": "strict"}, workspace={"level": "relaxed"})
        assert result.values == STRICT
        assert result.notes == ("! carter.yaml access.level ignored: can only harden",)

    def test_workspace_cannot_undo_a_user_override(self):
        result = resolve({"level": "guarded", "pr_write": "denied"}, workspace={"level": "guarded"})
        assert result.values["pr_write"] == "denied"

    def test_invalid_row_counts_as_denied(self):
        result = resolve({"level": "relaxed"}, workspace={"pr_write": "maybe"})
        assert result.values["pr_write"] == "denied"
        assert result.notes == ("! carter.yaml access.pr_write invalid: using denied",)

    def test_row_above_its_max_counts_as_denied(self):
        result = resolve({"level": "relaxed"}, workspace={"destructive": "allowed"})
        assert result.values["destructive"] == "denied"

    def test_invalid_level_counts_as_strict(self):
        result = resolve({"level": "relaxed"}, workspace={"level": "wide-open"})
        assert result.values == STRICT
        assert result.notes == ("! carter.yaml access.level invalid: using strict",)

    def test_workspace_that_is_not_a_table_counts_as_strict(self):
        result = resolve({"level": "relaxed"}, workspace="relaxed")
        assert result.values == STRICT
        assert result.notes == ("! carter.yaml access invalid: using strict",)

    @pytest.mark.parametrize("key", [*FLOOR_IDS, "gitcommit"])
    def test_unknown_and_floor_keys_are_ignored_with_a_line(self, key):
        result = resolve({"level": "guarded"}, workspace={key: "denied"})
        assert result.values == resolve({"level": "guarded"}).values
        assert result.notes == (f"! carter.yaml access.{key} unknown: ignored",)

    def test_hostile_workspace_key_stays_within_80_chars(self):
        result = resolve(None, workspace={"\x00" * 100: "denied"})
        _lines_ok(result)
        assert "\x00" not in result.notes[0]

    def test_a_user_error_still_lets_the_workspace_harden(self):
        result = resolve({"level": "nope"}, workspace={"pr_write": "denied"})
        assert result.values["pr_write"] == "denied"
        assert result.values["workspace_edit"] == "allowed"


class TestPolicyLevelAlias:
    def test_alias_works_like_access_level_with_one_deprecation_line(self):
        result = resolve({"level": "relaxed"}, workspace_policy_level="strict")
        assert result.values == STRICT
        assert result.notes == ("! carter.yaml policy.level is deprecated: use access.level",)

    def test_alias_looser_than_the_user_is_ignored(self):
        result = resolve({"level": "strict"}, workspace_policy_level="guarded")
        assert result.values == STRICT
        assert "! carter.yaml policy.level ignored: can only harden" in result.notes

    def test_unknown_alias_value_means_strict(self):
        result = resolve({"level": "relaxed"}, workspace_policy_level="paranoid")
        assert result.values == STRICT
        assert "! carter.yaml policy.level invalid: using strict" in result.notes

    def test_both_set_the_stricter_wins(self):
        result = resolve(
            {"level": "relaxed"}, workspace={"level": "guarded"}, workspace_policy_level="strict"
        )
        assert result.values == STRICT
        result = resolve(
            {"level": "relaxed"}, workspace={"level": "strict"}, workspace_policy_level="guarded"
        )
        assert result.values == STRICT

    def test_alias_note_fits_the_output_rule(self):
        result = resolve(None, workspace_policy_level="guarded")
        _lines_ok(result)
        assert max(map(len, result.notes)) <= 60


class TestRoles:
    @pytest.mark.parametrize("role", ["pm", "narrator", "engineer", "security", "devops"])
    def test_destructive_follows_the_level_for_every_local_write_role(self, role):
        assert resolve({"level": "guarded"}, role=role).values["destructive"] == "ask"

    @pytest.mark.parametrize("role", ["maestro", "architect", "learner"])
    def test_read_only_roles_never_get_destructive(self, role):
        result = resolve({"level": "guarded"}, role=role)
        assert (result.values["destructive"], result.sources["destructive"]) == ("denied", "role")

    def test_infra_apply_is_devops_only(self):
        assert resolve({"level": "guarded"}, role="devops").values["infra_apply"] == "ask"
        for role in ("engineer", "pm", "maestro"):
            assert resolve({"level": "guarded"}, role=role).values["infra_apply"] == "denied"

    def test_unknown_role_gets_neither(self):
        values = resolve({"level": "relaxed"}, role="intruder").values
        assert (values["destructive"], values["infra_apply"]) == ("denied", "denied")

    def test_no_role_means_no_role_cap(self):
        assert resolve({"level": "guarded"}).values["infra_apply"] == "ask"

    def test_role_never_loosens(self):
        assert resolve(None, role="devops").values == STRICT

    def test_the_strict_default_denies_devops_destructive_and_infra(self):
        """For an existing user on the new default, devops' destructive and infra are denied."""
        values = resolve(None, role="devops").values
        assert (values["destructive"], values["infra_apply"]) == ("denied", "denied")


class TestWarnings:
    def test_nothing_to_say_when_all_is_fine(self):
        assert warnings(resolve(None)) == ()

    def test_a_token_that_can_write_pull_requests_can_approve(self):
        assert warnings(resolve(None), token_writes={"pull_requests"}) == (
            "! token can approve PRs: github_admin is text-gated",
        )

    def test_issues_write_scope_warns_unless_the_level_allows_issue_writes(self):
        lines = warnings(resolve({"level": "guarded"}), token_writes={"issues"})
        assert lines == ("! token has Issues: write: issue_write is text-gated",)
        relaxed = resolve({"level": "relaxed"})
        assert warnings(relaxed, token_writes={"issues"}) == ()

    def test_order_and_length(self):
        lines = warnings(resolve(None), token_writes={"issues", "pull_requests"})
        assert len(lines) == 2
        assert lines[0].startswith("! token can approve")
        assert all(len(line) <= 60 for line in lines)


class TestMissingGroupLines:
    ALL = ("g2", "hooks", "docker", "read-edit-denies", "config-edit")

    def test_every_group_present_means_no_line(self):
        assert missing_group_lines(self.ALL) == ()

    def test_one_line_per_missing_group_in_a_fixed_order_each_short(self):
        lines = missing_group_lines(())
        assert [ln.split()[1] for ln in lines] == [
            "g2",
            "read-edit-denies",
            "docker",
            "hooks",
            "config-edit",
        ]
        assert all(ln.startswith("! ") and len(ln) <= 60 for ln in lines)

    def test_a_line_names_the_floor_ids_that_are_not_denied(self):
        (line,) = missing_group_lines([g for g in self.ALL if g != "g2"])
        assert line == "! g2 off: push, gh_api, github_admin, sudo, carter_internals"

    def test_either_commit_hook_group_covers_the_commit_checks(self):
        have = [g for g in self.ALL if g != "hooks"]
        assert missing_group_lines(have) == ("! hooks off: agent commits are not checked",)
        assert missing_group_lines([*have, "repo_hooks"]) == ()

    def test_every_floor_id_is_named_by_the_group_that_backs_it(self):
        named = {i for ids in GROUP_FLOORS.values() for i in ids}
        assert named == set(FLOOR_IDS)  # carter_internals rides on g2 (verbs, env overrides)

    def test_check_gets_one_short_line_for_all_of_them(self):
        assert missing_groups_summary(missing_group_lines(self.ALL)) == ""
        assert missing_groups_summary(missing_group_lines(())) == (
            "! 5 guard groups missing (see: carter access)"
        )
        assert len(missing_groups_summary(missing_group_lines(()))) <= 60
        assert missing_groups_summary(missing_group_lines(self.ALL[1:])).startswith(
            "! 1 guard group "
        )


class TestEffectiveLevelAndUnreadableConfig:
    def test_effective_level_is_the_stricter_of_user_and_workspace(self):
        assert resolve({"level": "relaxed"}, workspace={"level": "guarded"}).effective_level == (
            "guarded"
        )
        assert resolve({"level": "guarded"}, workspace={"level": "relaxed"}).effective_level == (
            "guarded"
        )
        assert resolve(None).effective_level == "strict"

    def test_a_row_only_workspace_leaves_the_level_alone(self):
        assert resolve({"level": "relaxed"}, workspace={"pr_write": "denied"}).effective_level == (
            "relaxed"
        )

    def test_an_unreadable_config_is_strict_with_its_line_and_the_fallback(self):
        result = resolve(None, user_error="config.toml unreadable or not valid TOML")
        assert result.values == STRICT
        assert result.notes == ("config.toml unreadable or not valid TOML", FALLBACK)


class TestReadOnlyRolesAskBeforeWritingToGitHub:
    @pytest.mark.parametrize("level", LEVELS)
    @pytest.mark.parametrize("role", ["maestro", "architect", "learner", "intruder"])
    @pytest.mark.parametrize("cap", ["pr_write", "issue_write"])
    def test_capped_at_ask_at_every_level(self, level, role, cap):
        values = resolve({"level": level, cap: "allowed"}, role=role).values
        assert values[cap] in ("ask", "denied")
        assert resolve({"level": level}, role=role).sources[cap] in ("preset", "role")

    @pytest.mark.parametrize("role", ["pm", "narrator", "engineer", "security", "devops"])
    def test_a_writer_keeps_the_level(self, role):
        values = resolve({"level": "relaxed"}, role=role).values
        assert (values["pr_write"], values["issue_write"]) == ("allowed", "allowed")

    def test_no_role_means_no_cap(self):
        assert resolve({"level": "relaxed"}).values["issue_write"] == "allowed"

    def test_a_stricter_value_is_kept(self):
        assert resolve({"level": "strict"}, role="maestro").values["issue_write"] == "denied"
