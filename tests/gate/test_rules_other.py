"""gh, the other gated verbs, human-only Carter verbs and interpreters (plan 004 step 19)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gate.helpers import rule_of

DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "carter/identity/g2_rules.json").read_text()
)
ALLOWED_GH = [e["verb"] for e in DATA["gh_read_allowlist"]]


class TestGh:
    @pytest.mark.parametrize("verb", ALLOWED_GH)
    def test_every_allowlisted_verb_passes_with_flags_after_the_subcommand(self, verb: str) -> None:
        assert rule_of(f"gh {verb} 12 --repo o/r --json number") is None
        assert rule_of(f"gh {verb}") is None

    @pytest.mark.parametrize(
        "cmd",
        [
            "gh pr create --title x --head feat/x",
            "gh pr create --fill",
            "gh pr edit 1 --add-label bug",
            "gh pr comment 1 --body done",
        ],
    )
    def test_pull_requests_may_be_opened_edited_and_commented_d72(self, cmd: str) -> None:
        assert rule_of(cmd) is None, cmd

    @pytest.mark.parametrize(
        "cmd",
        [
            "gh",
            "gh api user",
            "gh api -X POST x",
            "gh pr merge 1",
            "gh pr review 1",
            "gh pr close 1",
            "gh pr ready 1",
            "gh issue create",
            "gh issue comment 1",
            "gh release create v1",
            "gh repo create x",
            "gh repo delete x",
            "gh repo clone o/r",
            "gh workflow run x",
            "gh run rerun 1",
            "gh auth login",
            "gh auth token",
            "gh config set x y",
            "gh extension install x/y",
            "gh alias set x y",
            "gh gist create f",
            "gh secret set X",
            "gh variable set X",
            "gh ssh-key add k",
            "gh status",
            "gh --version",
            "gh pr",
        ],
    )
    def test_everything_else_is_refused(self, cmd: str) -> None:
        assert rule_of(cmd) == "other-verbs", cmd

    @pytest.mark.parametrize(
        "cmd",
        [
            "gh -R o/r pr view 1",
            "gh --repo o/r pr view 1",
            "gh --repo=o/r pr view 1",
            "gh -Ro/r pr view 1",
        ],
    )
    def test_a_leading_repo_flag_says_where_to_put_it(self, cmd: str) -> None:
        decision = __import__("carter.gate", fromlist=["check"]).check(cmd)
        assert decision.rule == "other-verbs" and "after the subcommand" in (decision.message or "")

    def test_paths_and_wrappers_do_not_hide_gh(self) -> None:
        for cmd in ("/usr/bin/gh api x", "env gh api x", "command gh api x", "sh -c 'gh api x'"):
            assert rule_of(cmd) == "other-verbs", cmd


class TestOtherVerbs:
    @pytest.mark.parametrize(
        "verb",
        [
            "sudo",
            "docker",
            "podman",
            "systemd-run",
            "crontab",
            "at",
            "doas",
            "pkexec",
            "tmux",
            "screen",
            "batch",
            "launchctl",
        ],
    )
    def test_refused_as_commands_only(self, verb: str) -> None:
        assert rule_of(f"{verb} x") == "other-verbs", verb
        assert rule_of(f"echo {verb} x") is None, verb
        assert rule_of(f"grep -r {verb} docs") is None, verb

    @pytest.mark.parametrize(
        "cmd", ["opencode run x", "opencode serve", "opencode run", "env opencode serve"]
    )
    def test_nested_opencode(self, cmd: str) -> None:
        assert rule_of(cmd) == "other-verbs"

    @pytest.mark.parametrize(
        "cmd",
        [
            "opencode",
            "opencode --version",
            "opencode debug config",
            "opencode models",
            "opencode session list",
        ],
    )
    def test_other_opencode_commands_pass(self, cmd: str) -> None:
        assert rule_of(cmd) is None

    @pytest.mark.parametrize("verb", ["sudo", "docker", "podman", "doas", "pkexec"])
    def test_a_declined_sudo_docker_group_lifts_exactly_these(self, verb: str) -> None:
        assert rule_of(f"{verb} x", skip=("sudo-docker",)) is None
        assert rule_of(f"{verb} x") == "other-verbs"

    def test_declining_that_group_changes_nothing_else(self) -> None:
        for cmd in (
            "git push",
            "systemd-run x",
            "gh api x",
            "cat ~/.ssh/id",
            "echo x > ~/.carter/isolation.json",
            "carter push",
            "tmux x",
        ):
            assert rule_of(cmd, skip=("sudo-docker",)) == rule_of(cmd) is not None, cmd

    def test_the_other_groups_skip_their_own_rules(self) -> None:
        assert rule_of("cat ~/.ssh/id", skip=("read-edit-denies",)) is None
        assert rule_of("echo x > ~/.carter/isolation.json", skip=("config-edit",)) is None
        assert rule_of("git push", skip=("g2",)) is None
        assert rule_of("sudo x", skip=("g2",)) == "other-verbs"

    def test_a_security_keychain_read(self) -> None:
        for sub in ("find-generic-password", "find-internet-password"):
            assert rule_of(f"security {sub} -s x") == "credential-paths"
        assert rule_of("security list-keychains") is None


class TestHumanOnlyCarter:
    @pytest.mark.parametrize(
        "cmd",
        [
            "carter push",
            "carter guard",
            "carter guard install",
            "carter guard remove --only plugin",
            "carter broker plan",
            "carter github-token set",
            "carter identity add",
            "carter identity remove x",
            "carter identity unlock",
            "carter identity lock",
            "carter --debug push",
            "python3 -m carter push",
            "/home/u/.local/bin/carter push",
            "env CARTER_X=1 carter push",
            # D68 g: the human tag lets the user's `!` shell push, so an agent must never forge it
            "CARTER_HUMAN_SHELL=1 carter push",
            "env CARTER_HUMAN_SHELL=1 carter push",
            "export CARTER_HUMAN_SHELL=1 && carter push",
            "unset CARTER_AGENT_SHELL && carter push",
        ],
    )
    def test_refused(self, cmd: str) -> None:
        assert rule_of(cmd) in ("human-only-carter", "env-overrides"), cmd
        if "CARTER_" not in cmd:
            assert rule_of(cmd) == "human-only-carter", cmd

    @pytest.mark.parametrize(
        "cmd",
        [
            "carter",
            "carter --help",
            "carter check",
            "carter check --host",
            "carter commit -m x",
            "carter ops config --emit",
            "carter gate check ls",
            "carter github-token check",
            "carter identity show",
            "carter identity verify",
            "carter identity env",
            "carter status",
            "echo carter push",
            "git commit -m 'carter push'",
        ],
    )
    def test_not_judged(self, cmd: str) -> None:
        assert rule_of(cmd) is None, cmd


class TestInterpreters:
    @pytest.mark.parametrize(
        "cmd",
        [
            "python3 -c 'import os; os.system(\"git status\")'",
            "python -c 'x=\"gh pr view\"'",
            "python3.12 -c 'git'",
            "python3 -Sc 'git'",
            "python3 -c\"print('git')\"",
            "perl -e 'system(\"git\")'",
            "perl -pe 's/a/git/'",
            "perl -E 'say git'",
            "ruby -e 'git'",
            "node -e 'git'",
            "node -p 'git'",
            "node --eval='git'",
            "node --print git",
            "php -r 'git();'",
            "lua -e 'git'",
            "awk 'BEGIN{system(\"git push\")}'",
            "gawk 'BEGIN{system(\"gh\")}'",
            "env python3 -c 'git'",
            "uv run python -c 'git'",
        ],
    )
    def test_program_text_that_mentions_git_or_gh_is_refused(self, cmd: str) -> None:
        assert rule_of(cmd) == "interpreter-git", cmd

    @pytest.mark.parametrize(
        "cmd",
        [
            "python3 -c 'print(1)'",
            "python3 -m pytest tests/test_git_x.py",
            "python3 script.py git",
            "python3 x.py --message 'git push'",
            "python3 -m json.tool x",
            "perl script.pl git",
            "node build.js git",
            "node --test tests/plugin/x.test.ts",
            "python3 -c 'import legit_gitlike'",
            "python3 -c 'digit = 1'",
            "ruby -e 'puts 1'",
            "awk '{print $1}' f",
            "python3 --version",
            "python3 -c 'print(\"github.com\")'",
        ],
    )
    def test_everything_else_passes(self, cmd: str) -> None:
        assert rule_of(cmd) is None, cmd

    def test_sudo_docker_podman_in_program_text(self) -> None:
        assert rule_of("python3 -c \"import os; os.system('sudo ls')\"") == "other-verbs"
        assert rule_of("python3 -c \"os.system('docker ps')\"", skip=("sudo-docker",)) is None

    def test_program_text_naming_credentials_or_control_files(self) -> None:
        assert rule_of("python3 -c \"open('/home/u/.ssh/id_rsa').read()\"") == "credential-paths"
        assert rule_of("python3 -c \"open('x/.carter/isolation.json','w')\"") == "control-files"
        assert rule_of("python3 -c \"open('x/.carter/memories/n.md','w')\"") is None
        assert rule_of("python3 -c \"open('.sshfoo/x')\"") is None

    def test_a_script_path_is_not_inspected_an_accepted_residual(self) -> None:
        assert rule_of("python3 scripts/does_git_things.py") is None


class TestOpencodeService:
    """Plan 004 step 36 (security review): a service restarted from an agent shell would inherit
    that shell's isolated environment (no SSH agent, agent signals) and degrade the human's
    `!` shells. Reads of the service stay allowed."""

    @pytest.mark.parametrize("sub", ["start", "restart", "stop", "set port 4000", "unset port"])
    def test_mutating_the_service_is_refused(self, sub: str) -> None:
        assert rule_of(f"opencode service {sub}") == "other-verbs"
        assert rule_of(f"env opencode service {sub}") == "other-verbs"

    @pytest.mark.parametrize("sub", ["status", "get", "get port"])
    def test_reads_pass(self, sub: str) -> None:
        assert rule_of(f"opencode service {sub}") is None

    def test_the_message_says_why(self) -> None:
        from carter import gate

        message = gate.check("opencode service restart").message or ""
        assert "inherit this shell's environment" in message and message.startswith("Refused by")
