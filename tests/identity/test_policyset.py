"""``policy_set`` and friends in ``g2_rules.json`` (RFC-0007 App C.1, C.6.3; plan 003 step 8)."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

import pytest

from carter.identity import policyset
from carter.identity.policyset import (
    Statement,
    gh_allowlist,
    policy_set,
    policy_statements,
    render_policies,
)
from carter.identity.rules import forbidden_classes, load_rules

HOME = "/home/fixture"
FROZEN_GROUPS = {"g2", "sudo-docker", "read-edit-denies", "config-edit"}


def raw() -> dict:
    text = resources.files("carter.identity").joinpath("g2_rules.json").read_text("utf-8")
    return json.loads(text)


def glob(pattern: str, value: str) -> bool:
    """OpenCode's whole-value wildcard: ``*`` zero or more chars, ``?`` one; a trailing
    ` *` also matches the bare command (policies docs, "Matching")."""
    if pattern.endswith(" *") and value == pattern[:-2]:
        return True
    rx = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(rx, value, flags=re.DOTALL) is not None


def decide(statements: list[Statement], action: str, value: str) -> str:
    """Last match wins; nothing matching means allowed (the policies docs, "Order")."""
    verdict = "allow"
    for st in statements:
        if st.action == "tool.use" and glob(st.resource, f"{action}:{value}"):
            verdict = st.effect
    return verdict


@pytest.fixture
def statements() -> list[Statement]:
    return list(policy_statements(home=HOME))


class TestOldLoaderContract:
    def test_slice_1_keys_keep_their_shape(self) -> None:
        data = raw()
        assert data["version"] == 1
        for key in ("agent_signals", "human_signals", "forbidden", "credential_paths"):
            assert data[key]
        assert load_rules().credential_paths[0] == "/.ssh/"

    def test_nothing_is_reserved_after_2a(self) -> None:  # 1G filled two keys, 2a the last
        assert raw()["reserved"] == []
        assert raw()["isolation_vars"]

    def test_filled_keys_are_not_empty_any_more(self) -> None:
        assert raw()["policy_set"] and raw()["gh_read_allowlist"]

    def test_new_keys_are_additive(self) -> None:
        assert {"consent_groups", "agent_permission_denies"} <= raw().keys()

    def test_credential_and_control_paths_are_untouched(self) -> None:
        assert "~/.carter/guard-state.json" in raw()["control_paths"]
        assert "/.carter/secrets/" in raw()["credential_paths"]

    def test_current_slice_is_1g_after_step_22(self) -> None:
        from carter.identity.rules import CURRENT_SLICE

        assert CURRENT_SLICE == "1G"


class TestStatementShape:
    def test_entries_have_the_frozen_fields(self) -> None:
        for entry in raw()["policy_set"]:
            assert set(entry) == {"id", "group", "action", "resource", "effect", "rfc"}, entry

    def test_groups_are_in_the_frozen_set(self) -> None:
        assert {e["group"] for e in raw()["policy_set"]} == FROZEN_GROUPS

    def test_every_statement_belongs_to_a_known_live_group(self) -> None:
        live = {g.id for g in policyset.consent_groups() if g.live}
        assert {s.group for s in policy_set()} <= live

    def test_data_holds_only_tool_use_denies(self) -> None:
        # gh allows are generated from gh_read_allowlist; D52 allows are computed.
        assert {(e["action"], e["effect"]) for e in raw()["policy_set"]} == {("tool.use", "deny")}

    def test_resources_are_action_colon_value(self) -> None:
        for st in policy_set():
            assert re.match(r"^(shell|read|edit):\S", st.resource), st.id

    def test_every_statement_cites_its_rfc_row(self) -> None:
        assert all(s.rfc for s in policy_set())

    def test_sudo_docker_holds_only_sudo_docker_podman_denies(self) -> None:
        group = [s for s in policy_set() if s.group == "sudo-docker"]
        assert {s.effect for s in group} == {"deny"}
        assert {s.resource.split()[0] for s in group} <= {
            "shell:sudo",
            "shell:docker",
            "shell:podman",
        }

    def test_the_consent_group_map_is_total(self) -> None:
        groups = {g.id for g in policyset.consent_groups()}
        assert all(s.group in groups for s in policy_set())
        # ... and each live group has at least one statement
        assert {g.id for g in policyset.consent_groups() if g.live} <= {
            s.group for s in policy_set()
        }

    def test_reserved_groups_have_no_statements(self) -> None:
        assert not [s for s in policy_set() if s.group in {"hooks", "alias", "repo_hooks"}]


class TestPushVerbsAreDenied:
    def test_every_forbidden_push_literal_has_a_deny(self, statements) -> None:
        (push,) = [c for c in forbidden_classes(all_slices=True) if c.id == "push-verbs"]
        for verb in push.items:
            assert decide(statements, "shell", f"{verb} origin main") == "deny", verb
            assert decide(statements, "shell", verb) == "deny", verb

    def test_no_allow_statement_can_lift_a_forbidden_verb(self, statements) -> None:
        allows = [s for s in statements if s.effect == "allow"]
        for cls in forbidden_classes(all_slices=True):
            if cls.id not in {"push-verbs"}:
                continue
            for lit in cls.literals:
                assert not [a for a in allows if glob(a.resource, f"shell:{lit}")], lit

    def test_sudo_and_docker_are_denied(self, statements) -> None:
        for cmd in ("sudo rm -rf /", "docker run x", "docker"):
            assert decide(statements, "shell", cmd) == "deny", cmd


class TestGhAllowlist:
    def test_is_the_rfc_list_minus_gh_status(self) -> None:
        verbs = [v.verb for v in gh_allowlist()]
        assert verbs == [
            "pr view", "pr list", "pr diff", "pr checks", "issue view", "issue list",
            "run view", "run list", "repo view", "search",
        ]  # fmt: skip

    def test_gh_status_was_dropped_after_spike_4_and_nothing_is_pending(self, statements) -> None:
        # Spike 4: `gh status` -> HTTP 403 "Resource not accessible by personal access token".
        assert "status" not in [v.verb for v in gh_allowlist()]
        assert [v for v in gh_allowlist() if v.pending] == []
        assert decide(statements, "shell", "gh status") == "deny"
        assert "gh status" in raw()["gh_notes"]["dropped"] and "403" in raw()["gh_notes"]["dropped"]

    def test_repo_view_and_search_repos_are_positional_not_dash_r(self) -> None:
        note = raw()["gh_notes"]["positional"]
        assert "gh repo view <owner>/<repo>" in note and "gh search repos <query>" in note
        assert "never `-R`" in note and "after the subcommand" in note

    def test_gh_api_is_never_allowed(self, statements) -> None:
        for cmd in ("gh api repos/o/r", "gh api -X POST /x", "gh api"):
            assert decide(statements, "shell", cmd) == "deny", cmd
        assert not [v for v in gh_allowlist() if v.verb.split()[0] == "api"]

    def test_write_verbs_stay_denied(self, statements) -> None:
        for cmd in (
            "gh pr create --title x",
            "gh pr merge 3",
            "gh pr comment 3 -b x",
            "gh issue create",
            "gh release create v1",
            "gh repo delete x",
            "gh auth login",
            "gh pr checkout 3",
        ):
            assert decide(statements, "shell", cmd) == "deny", cmd

    def test_allowlisted_reads_pass(self, statements) -> None:
        for cmd in (
            "gh pr view 3 --json title",
            "gh pr list",
            "gh pr diff 3",
            "gh pr checks 3",
            "gh issue view 4 -R o/r",
            "gh issue list",
            "gh run view 9 --log",
            "gh run list",
            "gh repo view o/r",
            "gh search prs foo",
            "gh search repos carter",
        ):
            assert decide(statements, "shell", cmd) == "allow", cmd

    def test_a_leading_repo_flag_fails_closed_by_construction(self, statements) -> None:
        # The gate (2a) rejects it with a message; the statements simply never match.
        assert decide(statements, "shell", "gh -R o/r pr view 3") == "deny"
        assert decide(statements, "shell", "gh --repo o/r pr view 3") == "deny"

    def test_no_statement_mentions_the_repo_flag(self, statements) -> None:
        assert not [s for s in statements if "-R" in s.resource or "--repo" in s.resource]
        assert "gate" in raw()["gh_notes"]["leading_repo_flag"]

    def test_allows_come_after_every_deny(self, statements) -> None:
        effects = [s.effect for s in statements]
        assert effects == sorted(effects, key=lambda e: e == "allow")  # all denies, then allows
        assert effects[-1] == "allow"


class TestReadAndEditDenies:
    @pytest.mark.parametrize(
        "path",
        [
            "/home/fixture/.ssh/id_ed25519",
            "/home/fixture/.config/gh/hosts.yml",
            "/home/fixture/.config/opencode/service.json",
            "/home/fixture/.git-credentials",
            "/home/fixture/.carter/secrets/gh-read.token",
        ],
    )
    def test_credential_paths_cannot_be_read(self, statements, path: str) -> None:
        assert decide(statements, "read", path) == "deny"

    def test_credential_path_data_is_covered(self, statements) -> None:
        # The five segments of C.1 that the read tool can reach (the rest is gate-only).
        covered = {
            "/.ssh/",
            "/.config/gh/",
            "opencode/service.json",
            "/.git-credentials",
            "/.carter/secrets/",
        }
        assert covered <= set(load_rules().credential_paths)

    def test_ordinary_files_stay_readable(self, statements) -> None:
        for path in (
            "/home/fixture/work/src/app.py",
            "src/app.py",
            "/home/fixture/.carter/memories/x.md",
        ):
            assert decide(statements, "read", path) == "allow", path

    @pytest.mark.parametrize(
        "path",
        [
            "/home/fixture/.config/opencode/opencode.json",
            "/home/fixture/.config/opencode/opencode.jsonc",
            "opencode.json",
            "opencode.jsonc",
            "sub/dir/opencode.jsonc",
            "/ws/opencode.json",
            ".opencode/agents/x.md",
            "/ws/.opencode/plugins/p.ts",
            ".git/hooks/pre-commit",
            "/ws/repo/.git/hooks/pre-push",
            ".git/config",
            "/ws/repo/.git/config",
            "/home/fixture/.ssh/config",
            "/home/fixture/.gitconfig",
            "/home/fixture/.config/git/config",
            "/home/fixture/.config/git/ignore",
            "/home/fixture/.carter/config.toml",
            "/home/fixture/.carter/bin/carter-guard",
            "/home/fixture/.carter/hooks/allowed_signers",
            "/home/fixture/.carter/run/agent.pid",
            "/home/fixture/.carter/secrets/gh-read.token",
            "/home/fixture/.carter/state/audit/b.jsonl",
            "/home/fixture/.carter/isolation.json",
            "/home/fixture/.carter/gitconfig",
            "/home/fixture/.carter/gitconfig.d/abc123",
            "/home/fixture/.carter/guard-state.json",
            "/home/fixture/.config/opencode/plugins/carter-guard.ts",
        ],
    )
    def test_control_plane_cannot_be_edited(self, statements, path: str) -> None:
        assert decide(statements, "edit", path) == "deny"

    def test_memories_and_ordinary_files_stay_editable(self, statements) -> None:
        for path in (
            "/home/fixture/.carter/memories/user/note.md",
            "src/app.py",
            "/ws/docs/README.md",
            ".carter/state/plans/active/x.md",
            "/home/fixture/.carter/manifest.json",
        ):
            assert decide(statements, "edit", path) == "allow", path

    def test_control_paths_data_is_covered_by_edit_denies(self, statements) -> None:
        for entry in load_rules().control_paths:
            sample = entry.replace("~", HOME)
            sample = sample + "x" if sample.endswith("/") else sample
            assert decide(statements, "edit", sample) == "deny", entry

    def test_section_4_5_extra_edit_list_is_covered(self, statements) -> None:
        for sample in (
            "/h/.config/opencode/opencode.jsonc",  # global opencode config
            "opencode.json",
            ".opencode/x",
            ".git/hooks/x",
            ".git/config",
            "/h/.ssh/x",
            "/h/.gitconfig",
            "/h/.config/git/config",
            "/h/.carter/config.toml",
        ):
            home_sample = sample.replace("/h/", f"{HOME}/")
            assert decide(statements, "edit", home_sample) == "deny", sample


class TestRendering:
    def test_home_placeholder_is_rendered_and_never_left_behind(self) -> None:
        text = json.dumps(render_policies(policy_statements(home=HOME)))
        assert "<home>" not in text and HOME in text

    def test_rendering_twice_is_byte_identical(self) -> None:
        a = json.dumps(render_policies(policy_statements(home=HOME)), indent=2)
        b = json.dumps(render_policies(policy_statements(home=HOME)), indent=2)
        assert a == b

    def test_rendered_shape_is_the_opencode_statement(self) -> None:
        for st in render_policies(policy_statements(home=HOME)):
            assert set(st) == {"action", "resource", "effect"}

    def test_groups_filter_statements_and_gh_allows_follow_g2(self) -> None:
        only_sudo = policy_statements(("sudo-docker",), home=HOME)
        assert {s.group for s in only_sudo} == {"sudo-docker"}
        assert not [s for s in only_sudo if s.effect == "allow"]
        no_g2 = policy_statements(("read-edit-denies", "config-edit"), home=HOME)
        assert not [s for s in no_g2 if s.id.startswith(("allow-gh", "deny-gh"))]

    def test_unknown_or_reserved_group_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="nope"):
            policy_statements(("nope",), home=HOME)
        assert policy_statements(("alias",), home=HOME) == ()

    def test_relative_home_is_refused(self) -> None:
        with pytest.raises(ValueError, match="absolute"):
            policy_statements(home="relative/dir")

    def test_home_with_glob_characters_is_refused(self) -> None:
        # A literal * or ? in $HOME would turn a deny into a wildcard.
        with pytest.raises(ValueError, match="glob"):
            policy_statements(home="/home/we*ird")

    def test_ids_are_not_part_of_the_rendered_statement(self) -> None:
        assert all("id" not in s for s in render_policies(policy_statements(home=HOME)))


class TestPerAgentBlock:
    def test_denies_are_carter_push_and_pr_and_not_global(self) -> None:
        assert policyset.agent_permission_denies() == ("carter_push", "carter_pr")
        for st in policy_set():
            assert "carter_push" not in st.resource and "carter_pr" not in st.resource

    def test_the_exemption_is_devops_only(self) -> None:
        assert policyset.agent_permission_exempt() == ("devops",)

    def test_mcp_deny_is_a_data_driven_list_of_roles(self) -> None:
        action, roles = policyset.agent_mcp_denies()
        assert action == "carter_github_*"
        assert isinstance(roles, tuple) and "devops" not in roles


class TestPackaging:
    def test_file_is_valid_strict_json_and_ships(self) -> None:
        data = json.loads(
            (Path(policyset.__file__).parent / "g2_rules.json").read_text(encoding="utf-8")
        )
        assert data["version"] == 1

    def test_policyset_is_stdlib_only(self) -> None:
        import ast
        import sys

        tree = ast.parse(Path(policyset.__file__).read_text(encoding="utf-8"))
        roots = {
            (n.module or "").split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.level == 0
        } | {
            a.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for a in n.names
        }
        assert roots <= set(sys.stdlib_module_names) | {"carter"}
