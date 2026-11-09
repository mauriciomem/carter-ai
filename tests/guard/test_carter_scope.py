"""G2 applies only to Carter agents (global install) and Carter workspaces.

The deny set moves from the OpenCode config's global ``policies`` into each Carter agent's own
``permissions:``. ``guard install`` takes out what an earlier Carter wrote there and says so in one
line; the only global write left is the per-agent ``carter_push`` denies of the built-in agents.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner, Result

from carter.cli import main
from carter.guard import agent_rules, hooks
from carter.guard.state import GuardState, load
from carter.identity.policyset import render_policies
from carter.install.mcp import config_target
from carter.install.paths import guard_state_path
from guard.helpers import decline, verbose

NOTICE = (
    "✓ the guards now apply only to Carter agents and Carter workspaces; "
    "global OpenCode policies removed."
)
BUILTINS = ["build", "plan", "general", "explore"]


def guard(*args: str) -> Result:
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False)


def carter_install(stack) -> Result:
    stack.fake()
    res = CliRunner().invoke(main, ["install", "--yes"], catch_exceptions=False)
    assert res.exit_code == 0, res.output
    return res


def agent_file(home: Path, role: str = "engineer") -> dict:
    text = (home / ".config" / "opencode" / "agents" / f"carter-{role}.md").read_text()
    return yaml.safe_load(text.split("---", 2)[1])


def shell_rules(front: dict) -> list[tuple[str, str]]:
    return [(r["resource"], r["effect"]) for r in front["permissions"] if r["action"] == "shell"]


def config_data() -> dict:
    return json.loads(config_target(None).read_text())


class TestTranslation:
    def test_a_statement_becomes_an_agent_rule(self) -> None:
        from carter.identity.policyset import Statement

        got = agent_rules.to_rule(Statement("i", "g2", "tool.use", "shell:git push *", "deny"))
        assert got == {"action": "shell", "resource": "git push *", "effect": "deny"}
        edit = Statement("j", "config-edit", "tool.use", "edit:/h/.carter/config.toml", "deny")
        assert agent_rules.to_rule(edit) == {
            "action": "edit", "resource": "/h/.carter/config.toml", "effect": "deny",
        }  # fmt: skip

    def test_nothing_installed_means_no_rules(self) -> None:
        assert agent_rules.current_rules() == []

    def test_accepted_groups_give_denies_then_allows(self, home: Path) -> None:
        state = GuardState()
        for group in ("g2", "sudo-docker", "read-edit-denies", "config-edit"):
            state.consent(group, "accepted", "2026-01-01", 1)
        rules = agent_rules.rules_for(state, home=str(home))
        effects = [r["effect"] for r in rules]
        assert effects == sorted(effects, key=lambda e: e == "allow")  # denies first
        got = {(r["action"], r["resource"], r["effect"]) for r in rules}
        assert ("shell", "git push *", "deny") in got and ("shell", "gh *", "deny") in got
        assert ("shell", "gh pr create *", "allow") in got
        assert ("shell", "gh pr merge *", "allow") not in got
        assert ("read", "*/.ssh/*", "deny") in got
        assert ("edit", f"{home}/.carter/config.toml", "deny") in got

    def test_a_declined_group_is_left_out(self, home: Path) -> None:
        state = GuardState()
        state.consent("g2", "accepted", "2026-01-01", 1)
        state.consent("sudo-docker", "declined", "2026-01-01", 1)
        resources = {r["resource"] for r in agent_rules.rules_for(state, home=str(home))}
        assert (
            "git push *" in resources and "sudo *" not in resources and "docker *" not in resources
        )


class TestRendering:
    def test_the_rules_come_last_in_every_agent(self, home: Path) -> None:
        from carter.config import generate_default_config, permission_rules, with_guard_rules

        config = generate_default_config()
        extra = [{"action": "shell", "resource": "zz *", "effect": "deny"}]
        rules = permission_rules(with_guard_rules(config, extra), "engineer")
        assert rules[-1] == extra[0]
        assert permission_rules(config, "engineer") == rules[:-1]

    def test_render_agents_reads_this_machines_guard_state(self, home: Path) -> None:
        from carter.config import generate_default_config
        from carter.scaffold import create_env, render_agents

        config = generate_default_config()
        plain = render_agents(config, create_env())["carter-engineer-local.md"]
        state = GuardState()
        state.consent("g2", "accepted", "2026-01-01", 1)
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        from carter.guard.state import save

        save(state, path)
        guarded = render_agents(config, create_env())["carter-engineer-local.md"]
        assert plain != guarded and "git send-pack *" in guarded

    def test_lint_uses_the_same_rules_as_the_render(self, home: Path) -> None:
        from carter.config import generate_default_config
        from carter.plans import parse_frontmatter
        from carter.scaffold import create_env, lint_policy, render_agents

        config = generate_default_config()
        state = GuardState()
        state.consent("g2", "accepted", "2026-01-01", 1)
        from carter.guard.state import save

        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        save(state, path)
        rendered = render_agents(config, create_env())
        installed = {
            role: parse_frontmatter(rendered[f"carter-{role}-local.md"])
            for role in config["agents"]
        }
        assert lint_policy(config, installed) == []


class TestGuardInstall:
    def test_no_global_policies_are_written_and_the_agent_files_carry_the_set(
        self, stack, home: Path
    ) -> None:
        carter_install(stack)
        cfg = config_data()
        assert "policies" not in cfg
        for name in BUILTINS:  # the one global write left: carter_push, hiding the tool
            assert [r["action"] for r in cfg["agents"][name]["permissions"]] == ["carter_push"]
        front = agent_file(home)
        rules = shell_rules(front)
        assert ("git push *", "deny") in rules and ("gh *", "deny") in rules
        assert ("gh pr create *", "allow") in rules
        assert rules.index(("gh *", "deny")) < rules.index(("gh pr create *", "allow"))
        assert ("gh pr merge *", "deny") in rules
        assert any(
            r["action"] == "read" and r["resource"] == "*/.ssh/*" for r in front["permissions"]
        )

    def test_every_carter_agent_gets_them_and_devops_keeps_carter_push(
        self, stack, home: Path
    ) -> None:
        carter_install(stack)
        for role in (
            "maestro",
            "architect",
            "engineer",
            "devops",
            "pm",
            "learner",
            "narrator",
            "security",
        ):
            assert ("git push *", "deny") in shell_rules(agent_file(home, role)), role
        pushes = [
            r for r in agent_file(home, "devops")["permissions"] if r["action"] == "carter_push"
        ]
        assert pushes == []
        assert [r for r in agent_file(home)["permissions"] if r["action"] == "carter_push"]

    def test_a_declined_group_is_left_out_of_the_agent_files(self, stack, home: Path) -> None:
        stack.fake()
        decline("sudo-docker")
        assert guard("install", "--yes").exit_code == 0
        # no manifest yet (no `carter install`): the guard step alone writes no agent file
        assert not (home / ".config" / "opencode" / "agents").exists()
        res = CliRunner().invoke(main, ["install", "--yes"], catch_exceptions=False)
        assert res.exit_code == 0, res.output
        resources = {
            r["resource"] for r in agent_file(home)["permissions"] if r["action"] == "shell"
        }
        assert "git push *" in resources and "sudo *" not in resources

    def test_the_manifest_records_the_rewritten_agent_hashes(self, stack, home: Path) -> None:
        from carter.install.ownership import sha256_bytes

        carter_install(stack)
        manifest = json.loads((home / ".carter" / "manifest.json").read_text())
        path = home / ".config" / "opencode" / "agents" / "carter-engineer.md"
        assert manifest["file_hashes"][str(path)] == sha256_bytes(path.read_bytes())
        assert manifest["files"].count(str(path)) == 1

    def test_the_second_run_changes_nothing(self, stack, home: Path) -> None:
        carter_install(stack)
        path = home / ".config" / "opencode" / "agents" / "carter-engineer.md"
        before = path.read_bytes()
        assert guard("install", "--yes").exit_code == 0
        assert path.read_bytes() == before

    def test_print_policies_is_gone(self) -> None:
        res = CliRunner().invoke(main, ["guard", "install", "--print-policies"])
        assert res.exit_code == 2 and "no such option" in res.output.lower()


class TestUpgradeFromGlobalPolicies:
    """An earlier Carter wrote the deny set into the OpenCode config's ``policies``."""

    def seed(self, home: Path) -> list:
        from carter.identity.policyset import policy_statements

        statements = list(policy_statements(home=str(home)))
        mine = {"action": "tool.use", "resource": "shell:my-own *", "effect": "deny"}
        cfg = config_target(None)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"policies": [mine, *render_policies(statements)], "providers": {"p": {}}})
        )
        state = GuardState()
        for group in ("g2", "sudo-docker", "read-edit-denies", "config-edit"):
            state.consent(group, "accepted", "2026-01-01", 1)
        for s in statements:
            state.record_policy(s.id, s.action, s.resource, s.effect, preexisting=False)
        state.opencode_config = str(cfg)
        from carter.guard.state import save

        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        save(state, path)
        return statements

    def test_the_old_statements_go_the_notice_is_printed_and_yours_stay(
        self, stack, home: Path
    ) -> None:
        self.seed(home)
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert NOTICE in res.output
        cfg = config_data()
        assert cfg["policies"] == [
            {"action": "tool.use", "resource": "shell:my-own *", "effect": "deny"}
        ]
        assert cfg["providers"] == {"p": {}}
        assert load(guard_state_path(None)).opencode_policies == []

    def test_a_statement_you_already_had_is_never_removed(self, stack, home: Path) -> None:
        statements = self.seed(home)
        state = load(guard_state_path(None))
        first = statements[0]
        state.opencode_policies[0]["preexisting"] = True
        from carter.guard.state import save

        save(state, guard_state_path(None))
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        left = [p["resource"] for p in config_data()["policies"]]
        assert first.resource in left

    def test_the_notice_is_not_printed_when_there_was_nothing_to_remove(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes")
        assert NOTICE not in res.output and "global OpenCode policies removed" not in res.output

    def test_no_reconsent_and_no_revision_bump(self, stack, home: Path) -> None:
        self.seed(home)
        before = load(guard_state_path(None)).consents
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        after = load(guard_state_path(None)).consents
        assert {g: c["decision"] for g, c in after.items() if g in before} == {
            g: c["decision"] for g, c in before.items()
        }
        assert after["g2"]["rev"] >= before["g2"]["rev"]  # a bare --yes never moves a revision up

    def test_the_notice_shows_in_a_normal_run_not_only_with_v(self, stack, home: Path) -> None:
        self.seed(home)
        stack.fake()
        res = CliRunner().invoke(main, ["guard", "install", "--yes"], catch_exceptions=False)
        assert NOTICE in res.output


class TestRemove:
    def test_remove_takes_the_rules_out_of_the_agent_files(self, stack, home: Path) -> None:
        carter_install(stack)
        assert ("git push *", "deny") in shell_rules(agent_file(home))
        res = guard("remove")
        assert res.exit_code == 0, res.output
        assert ("git send-pack *", "deny") not in shell_rules(agent_file(home))

    def test_remove_only_a_group_leaves_the_others(self, stack, home: Path) -> None:
        carter_install(stack)
        assert guard("remove", "--only", "sudo-docker").exit_code == 0
        resources = {
            r["resource"] for r in agent_file(home)["permissions"] if r["action"] == "shell"
        }
        assert "sudo *" not in resources and "gh *" in resources


class TestStatusAndHost:
    def test_status_says_where_the_rules_live(self, stack, home: Path) -> None:
        carter_install(stack)
        out = guard("status").output
        assert "no global policies" in out and "Carter agent files carrying the guard rules" in out

    def test_status_flags_leftover_recorded_policies(self, stack, home: Path) -> None:
        TestUpgradeFromGlobalPolicies().seed(home)
        stack.fake()
        out = guard("status").output
        assert "still recorded" in out and "carter guard install" in out

    def test_check_host_warns_about_leftover_global_policies(self, stack, home: Path) -> None:
        from rows import check_host

        TestUpgradeFromGlobalPolicies().seed(home)
        stack.fake()
        out = check_host().output
        assert "WARN  agent files:" in out and "bind every agent" in out

    def test_check_host_is_red_for_a_drifted_agent_file(self, stack, home: Path) -> None:
        from rows import check_host

        carter_install(stack)
        path = home / ".config" / "opencode" / "agents" / "carter-engineer.md"
        path.write_text(path.read_text().replace("git push *", "git push --never *"))
        out = check_host().output
        assert "RED   agent files: carter-engineer.md" in out

    def test_check_host_is_green_after_install(self, stack, home: Path) -> None:
        from rows import check_host

        carter_install(stack)
        out = check_host().output
        assert "OK    agent files:" in out and "carry the guard rules" in out


class TestHooksOnlyActOnThePluginTag:
    @pytest.fixture
    def script(self, tmp_path: Path) -> Path:
        path = tmp_path / "carter-guard"
        path.write_text(hooks.render_script())
        path.chmod(0o755)
        return path

    @pytest.mark.parametrize(
        "env",
        [
            {"AGENT": "1"},
            {"OPENCODE_SESSION_ID": "ses_x"},
            {"OPENCODE": "1", "AI_AGENT": "opencode"},
            {},
        ],
    )
    def test_other_signals_alone_no_longer_block_a_push(self, script: Path, env: dict) -> None:
        import subprocess

        sh = shutil.which("dash") or "/bin/sh"
        done = subprocess.run(
            [sh, str(script), "pre-push", "origin", "url"],
            env={"PATH": "/usr/bin:/bin", **env}, capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert (done.returncode, done.stderr) == (0, "")

    def test_the_plugin_tag_still_blocks(self, script: Path) -> None:
        import subprocess

        sh = shutil.which("dash") or "/bin/sh"
        done = subprocess.run(
            [sh, str(script), "pre-push"],
            env={"PATH": "/usr/bin:/bin", "CARTER_AGENT_SHELL": "1"}, capture_output=True,
            text=True, check=False,
        )  # fmt: skip
        assert done.returncode == 1 and "CARTER_AGENT_SHELL=1" in done.stderr

    def test_the_oracle_matches(self) -> None:
        assert hooks.hook_is_agent({"CARTER_AGENT_SHELL": "1"}) is True
        assert hooks.hook_is_agent({"AGENT": "1", "OPENCODE": "1"}) is False
        assert hooks.hook_is_agent({"CARTER_AGENT_SHELL": "0"}) is False

    def test_python_rules_is_agent_is_unchanged(self) -> None:
        from carter.identity.rules import is_agent

        assert is_agent({"AGENT": "1"}) is True  # Carter's own CLI refusals keep the full AD1 test
