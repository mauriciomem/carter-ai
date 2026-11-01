"""``g2_rules.json`` (RFC-0007 App C.1, C.4.1): the single data file behind the skill's
forbidden list, the eval ``commands_not_contain`` lists and, later, the gate and guard.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import tomllib
from importlib import resources
from pathlib import Path

import pytest

from carter.identity import rules
from carter.identity.rules import (
    CURRENT_SLICE,
    forbidden_classes,
    load_rules,
    pollution_hits,
    render_forbidden_block,
    render_forbidden_commands,
    warn_hits,
)

REPO = Path(__file__).resolve().parents[2]

# App C.1 table: key -> required JSON type.
REQUIRED = {
    "agent_signals": list,
    "human_signals": list,
    "isolation_markers": list,
    "pollution_set": dict,
    "isolation_vars": list,
    "forbidden": list,
    "gh_read_allowlist": list,
    "policy_set": list,
    "credential_paths": list,
    "control_paths": list,
}


def raw() -> dict:
    text = resources.files("carter.identity").joinpath("g2_rules.json").read_text("utf-8")
    return json.loads(text)


class TestSchema:
    def test_has_a_version(self):
        assert isinstance(raw()["version"], int) and raw()["version"] >= 1

    @pytest.mark.parametrize(("key", "kind"), sorted(REQUIRED.items()))
    def test_required_keys_have_the_right_types(self, key, kind):
        assert isinstance(raw()[key], kind), key

    def test_signal_and_path_entries_are_strings(self):
        data = raw()
        for key in ("agent_signals", "human_signals", "credential_paths", "control_paths"):
            assert data[key] and all(isinstance(v, str) for v in data[key]), key

    def test_isolation_markers_are_structured(self):
        for marker in raw()["isolation_markers"]:
            assert set(marker) == {"name", "match", "value"}

    def test_reserved_keys_are_empty_and_named(self):
        data = raw()
        assert data["reserved"] == ["isolation_vars", "gh_read_allowlist", "policy_set"]
        for key in data["reserved"]:
            assert data[key] == [], f"{key} is reserved for a later slice"

    def test_every_forbidden_entry_is_traceable_and_complete(self):
        ids = set()
        for entry in raw()["forbidden"]:
            assert {"id", "class", "applies_from", "items", "literals", "rfc"} <= set(entry)
            assert entry["rfc"].startswith("C.4.1 row ")
            assert entry["items"] and all(isinstance(i, str) for i in entry["items"])
            assert all(isinstance(i, str) for i in entry["literals"])
            assert entry["applies_from"] in rules.SLICES
            assert entry["id"] not in ids
            ids.add(entry["id"])

    def test_json_is_comment_free_and_utf8(self):
        path = REPO / "carter" / "identity" / "g2_rules.json"
        assert json.loads(path.read_text(encoding="utf-8"))  # strict JSON: no comments


class TestValuesFollowTheRfc:
    def test_signals(self):
        r = load_rules()
        assert r.agent_signals == (
            "CARTER_AGENT_SHELL",
            "AGENT",
            "AI_AGENT",
            "OPENCODE",
            "OPENCODE_SESSION_ID",
        )
        assert r.human_signals == ("CARTER_HUMAN_SHELL",)

    def test_credential_paths_are_the_c1_segments(self):
        assert load_rules().credential_paths == (
            "/.ssh/",
            "/.config/gh/",
            "opencode/service.json",
            "/.git-credentials",
            "/proc/*/environ",
            "/Library/Keychains/",
            "/.carter/secrets/",
        )

    def test_control_paths_are_the_c1_entries(self):
        assert load_rules().control_paths == (
            "~/.carter/bin/",
            "~/.carter/hooks/",
            "~/.carter/run/",
            "~/.carter/isolation.json",
            "~/.carter/gitconfig",
            "~/.carter/config.toml",
            "~/.carter/guard-state.json",
            "<plugin dir>",
        )

    def test_isolation_markers_match_by_carters_exact_values(self):
        by_name = {m.name: m for m in load_rules().isolation_markers}
        assert by_name["GIT_SSH_COMMAND"].value == "IdentityAgent=none"
        assert by_name["DBUS_SESSION_BUS_ADDRESS"].value == "unix:path=/nonexistent"
        assert by_name["GH_CONFIG_DIR"].value == "<home>/.carter/run/gh-empty"


class TestPollution:
    def test_pollution_set_is_signals_plus_markers(self):
        r = load_rules()
        assert set(r.pollution_by_name) == set(r.agent_signals) | set(r.human_signals)
        assert set(r.pollution_by_value) == {m.name for m in r.isolation_markers}

    def test_signals_pollute_by_name_whatever_the_value(self):
        for name in (*load_rules().agent_signals, *load_rules().human_signals):
            assert pollution_hits({name: ""}, home="/h") == [name]
            assert pollution_hits({name: "anything"}, home="/h") == [name]

    @pytest.mark.parametrize(
        "env",
        [
            {"SSH_AUTH_SOCK": "/run/user/1000/keyring/ssh"},
            {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"},
            {"GH_CONFIG_DIR": "/home/u/.config/gh"},
            {"GIT_SSH_COMMAND": "ssh -i ~/.ssh/work"},
            {"PATH": "/usr/bin", "HOME": "/h"},
        ],
    )
    def test_normal_desktop_state_is_not_pollution(self, env):
        assert pollution_hits(env, home="/h") == []

    @pytest.mark.parametrize(
        ("env", "hit"),
        [
            ({"GIT_SSH_COMMAND": "ssh -o IdentityAgent=none"}, "GIT_SSH_COMMAND"),
            ({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"}, "DBUS_SESSION_BUS_ADDRESS"),
            ({"GH_CONFIG_DIR": "/h/.carter/run/gh-empty"}, "GH_CONFIG_DIR"),
        ],
    )
    def test_carters_own_isolation_values_are_pollution(self, env, hit):
        assert pollution_hits(env, home="/h") == [hit]

    def test_gh_tokens_are_a_warning_not_pollution(self):
        env = {"GH_TOKEN": "x", "GITHUB_TOKEN": "y"}
        assert pollution_hits(env, home="/h") == []
        assert warn_hits(env) == ["GH_TOKEN", "GITHUB_TOKEN"]

    def test_hits_never_carry_values(self):
        assert "secret" not in repr(pollution_hits({"AGENT": "secret"}, home="/h"))


class TestForbiddenCoversEveryClassOfC41:
    def test_every_class_of_the_rfc_table_is_present(self):
        classes = {e.class_ for e in forbidden_classes(all_slices=True)}
        assert classes == {
            "Commit-creating verbs",
            "Staging",
            "Push verbs",
            "Env prefixes, assignments and unsets",
            "git config",
            "-c and --config-env=",
            "Plumbing",
            "Other verbs",
            "Human-only Carter verbs",
            "Credential paths",
            "Control files",
        }

    def test_n_is_no_verify_only_for_commit(self):
        (entry,) = [e for e in forbidden_classes(all_slices=True) if e.id == "commit-flags"]
        assert [(f["flag"], f["verbs"]) for f in entry.scoped_flags] == [("-n", ["commit"])]
        assert set(entry.verbs) == {
            "commit",
            "merge",
            "rebase",
            "cherry-pick",
            "revert",
            "am",
            "pull",
        }

    def test_commit_flags_are_the_c41_row(self):
        (entry,) = [e for e in forbidden_classes(all_slices=True) if e.id == "commit-flags"]
        for flag in ("--no-verify", "--no-gpg-sign", "--signoff", "--reset-author", "--author"):
            assert any(flag in item for item in entry.items), flag

    def test_config_flag_keys_include_carter_star(self):
        (entry,) = [e for e in forbidden_classes(all_slices=True) if e.id == "config-flags"]
        assert "carter.*" in entry.items and "commit.gpgsign" in entry.items

    def test_staging_and_push_and_plumbing(self):
        by_id = {e.id: e for e in forbidden_classes(all_slices=True)}
        assert by_id["staging"].items == ("git add -A", "git add .", "git commit -a")
        assert "update-ref" in by_id["plumbing"].items
        assert by_id["push-verbs"].items == ("git push", "git send-pack")
        assert "commit-tree" in by_id["plumbing"].items
        assert "raw SHA" in by_id["plumbing"].note

    def test_slice_1_enforces_the_commit_recipe_not_the_gate_or_push_rules(self):
        enforced = {e.id for e in forbidden_classes()}
        assert CURRENT_SLICE == "1"
        assert {"commit-flags", "staging", "env-overrides", "git-config-writes"} <= enforced
        # devops pushing is unchanged until slice 1G; the gate is slice 2a
        assert not {"push-verbs", "other-verbs", "human-only-carter", "control-files"} & enforced

    def test_a_later_slice_extends_without_a_schema_change(self):
        later = {e.id for e in forbidden_classes(current="2a")}
        assert {"push-verbs", "other-verbs", "credential-paths"} <= later


class TestLoader:
    def test_is_pure_stdlib_and_uses_importlib_resources(self):
        src = (REPO / "carter" / "identity" / "rules.py").read_text(encoding="utf-8")
        assert "importlib" in src
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        import sys

        assert imported <= set(sys.stdlib_module_names) | {"carter"}

    def test_returns_frozen_structures(self):
        r = load_rules()
        assert dataclasses.is_dataclass(r)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.version = 9  # type: ignore[misc]
        assert isinstance(r.agent_signals, tuple)
        assert isinstance(forbidden_classes()[0].items, tuple)

    def test_loaded_once(self):
        assert load_rules() is load_rules()

    def test_file_ships_with_the_package(self):
        resource = resources.files("carter.identity").joinpath("g2_rules.json")
        assert resource.is_file()

    def test_wheel_build_config_includes_package_data(self):
        # hatch ships every non-ignored file under packages=["carter"], so the JSON is in
        # the wheel unless a build option narrows the selection (checked by hand: unzip -l).
        cfg = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        wheel = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]
        assert "carter" in wheel["packages"]
        for narrowing in ("only-include", "exclude", "include"):
            assert narrowing not in wheel, f"[wheel] {narrowing} could drop g2_rules.json"
        assert "g2_rules.json" not in (REPO / ".gitignore").read_text(encoding="utf-8")


class TestRenderers:
    def test_commands_are_deterministic_and_unique(self):
        first = render_forbidden_commands()
        assert first == render_forbidden_commands()
        assert len(first) == len(set(first))

    def test_commands_follow_the_data_file(self):
        expected = []
        for entry in raw()["forbidden"]:
            if rules.SLICES.index(entry["applies_from"]) <= rules.SLICES.index(CURRENT_SLICE):
                expected += [lit for lit in entry["literals"] if lit not in expected]
        assert render_forbidden_commands() == expected

    def test_slice_1_commands_cover_the_recipe_hazards(self):
        cmds = render_forbidden_commands()
        for needed in ("--author", "--no-verify", "git commit -S", "git add -A", "git add ."):
            assert needed in cmds
        assert "git push" not in cmds  # 1G

    def test_block_is_marked_and_names_every_enforced_item(self):
        block = render_forbidden_block()
        assert block.startswith("<!-- forbidden:begin -->\n")
        assert block.rstrip().endswith("<!-- forbidden:end -->")
        for entry in forbidden_classes():
            assert entry.class_ in block
            for item in entry.items:
                assert f"`{item}`" in block, item
            if entry.note:
                assert entry.note in block
        assert "git push" not in block

    def test_block_is_deterministic(self):
        assert render_forbidden_block() == render_forbidden_block()
