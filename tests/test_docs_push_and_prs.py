"""Pushing and pull requests in the docs match the code.

``carter push`` is the user's, ``carter_push`` is devops' with the user's approval, and agents
open pull requests with ``gh``. The numbers, codes and files the docs name are the code's own;
the GitHub token guide matches the package's MCP entry.
"""

from __future__ import annotations

import json
import re

import pytest
from click.testing import CliRunner

from carter.broker import audit, counter, plan
from carter.cli import main
from carter.guard import consent
from carter.identity.errors import registry
from carter.identity.schema import Github
from docs_support import REPO, codes_in, documented, help_options, norm, section, text

WRITE = "guides/write-operations.md"
PUSH_TOOL_CODES = (
    "E-B-DEFAULT", "E-B-HTTPS", "E-B-REPOCFG", "E-B-UNSIGNED", "E-B-NOAGENT", "E-B-POLLUTED",
    "E-B-MOVED", "E-B-DWELL", "E-B-TIMEOUT", "E-B-REJECTED", "E-B-ARGS", "E-B-HEADLESS",
)  # fmt: skip


def write_ops() -> str:
    raw = re.sub(r"^> ?", "", text(WRITE), flags=re.M)
    return norm(raw)


class TestTheFlow:
    def test_you_push_then_the_agent_opens_the_pr_then_you_decide(self) -> None:
        body = write_ops()
        i_push = body.index("You run `carter push`")
        i_pr = body.index("The agent opens the pull request")
        i_human = body.index("You decide what happens to the PR")
        assert i_push < i_pr < i_human
        for needle in (
            "carter push --dry-run",
            "the default branch too: nothing to type",
            "gh pr create --head <branch>",
            "Pull requests: write",
            "There are no options for forcing",
            "no agent pushes",
        ):
            assert needle in body, needle

    def test_carter_push_is_for_you_in_a_terminal_or_the_tagged_bang_shell(self) -> None:
        body = write_ops()
        assert "`carter push` is for you, not an agent" in body and "`!carter push`" in body
        assert "once the plugin has tagged it" in body

    def test_a_typed_bang_push_is_an_unvalidated_fallback(self) -> None:
        body = write_ops()
        assert "unvalidated fallback" in body
        assert "Type such lines yourself; never paste a line that starts with `!`" in body

    def test_issues_reviews_merges_and_releases_have_no_agent_path(self) -> None:
        assert "no agent path for issues, reviews, merges or releases" in write_ops()

    def test_the_commit_section_matches_the_emit(self) -> None:
        body = write_ops()
        assert "If the emit says `commits: refused`, the agent stops" in body
        assert "carter identity unlock" in body and "it is never made unsigned" in body
        assert "`Committed 4f9c2ab: feat(auth): add token refresh`" in body

    def test_nothing_mentions_a_handoff_or_a_pr_command(self) -> None:
        body = write_ops()
        for gone in ("handoff", "carter pr", "E-SECRET-SCAN", "E-HANDOFF"):
            assert gone not in body, gone


class TestCarterPush:
    def test_the_options_equal_help(self) -> None:
        block = section(text("reference/cli.md"), "carter push")
        assert (
            documented(block)
            == help_options("push")
            == {"--dry-run", "--set-upstream", "--verbose"}
        )

    def test_it_is_listed_and_there_is_no_pr_command(self) -> None:
        doc = text("reference/cli.md")
        assert "[`push`](#carter-push)" in doc and "\n## carter push\n" in doc
        assert "\n## carter pr\n" not in doc and "(#carter-pr)" not in doc
        assert "\n  pr " not in CliRunner().invoke(main, ["--help"]).output

    def test_it_is_for_a_human_and_asks_nothing(self) -> None:
        doc = norm(text("reference/cli.md"))
        assert "For a human only" in doc and "`!carter push`" in doc
        assert "no terminal is needed" in doc and "asks nothing" in doc


class TestCarterPushTool:
    def test_it_comes_with_g2_and_can_be_removed_alone(self) -> None:
        body = write_ops()
        assert "`carter_push`" in body and "carter guard remove --only broker" in body
        assert consent.BROKER == "broker"
        remove = section(text("reference/cli.md"), "carter guard remove", "###")
        assert "plugin|broker" in remove and "`broker` turns only" in remove

    def test_the_numbers_are_the_codes(self) -> None:
        body = write_ops()
        assert plan.DWELL_FLOOR_MS == 500 and "half a second" in body
        assert f"{plan.TIMEOUT_MS // 1000} seconds" in body
        assert counter.MAX_REJECTIONS == 3 and "Three rejections" in body
        assert f"{plan.DWELL_CAP_MS:,}".replace(",", " ") in body
        assert audit.ROTATE_BYTES > 0

    def test_it_is_a_convenience_not_a_boundary_and_says_so_twice(self) -> None:
        assert "`carter_push` is a convenience, not a security boundary" in write_ops()
        safety = norm(text("guides/safety-and-permissions.md"))
        assert "`carter_push` can be forged by a same-user agent" in safety

    def test_it_never_recommends_auto_accept(self) -> None:
        for risky in ("--auto", "auto-accept"):
            for sentence in re.findall(r"[^.]*" + re.escape(risky) + r"[^.]*\.", write_ops()):
                assert re.search(r"\b(not|never|refus|warn|stop|rejects|would be)", sentence)

    def test_every_refusal_code_is_in_the_guide_and_the_troubleshooting_table(self) -> None:
        trouble = text("troubleshooting.md")
        for code in PUSH_TOOL_CODES:
            assert code in registry(), code
            assert code in write_ops() or code in trouble, code
        assert codes_in(text(WRITE)) <= set(registry())

    def test_the_headless_profile_and_the_audit_files_are_documented(self) -> None:
        assert "OPENCODE_CONFIG=~/.carter/opencode-headless.json" in write_ops()
        files = norm(text("reference/files-and-paths.md"))
        for needle in ("state/audit/b.jsonl", "state/audit/audit.log", "b-rejections.json"):
            assert needle in files, needle

    def test_the_config_table_names_the_broker_keys(self) -> None:
        body = norm(text("reference/configuration.md"))
        assert "[broker]" in body and "min_dwell_ms" in body


class TestGithubToken:
    def doc(self) -> str:
        return norm(text("guides/mcp-servers.md"))

    def test_the_guide_follows_the_contract(self) -> None:
        body = self.doc()
        for needle in (
            "fine-grained personal access token",
            "Classic tokens (`ghp_`)",
            '"All repositories" is accepted but wider than needed',
            "`[github] probe_repo",
            "the repository's name is never printed",
            "**Pull requests: Read and write**",
            "90 days or less",
            "SAML single sign-on",
            "`carter github-token set`",
            "`carter github-token check`",
            "~/.carter/secrets/gh-read.token",
            "{file:~/.carter/secrets/gh-read.token}",
            "directory 0700, file 0600",
            "Treat it as disclosed to your model provider",
        ):
            assert needle in body, needle

    def test_a_missing_token_is_a_warning_at_install_but_the_server_fails_to_start(self) -> None:
        body = self.doc()
        assert "does not stop the install" in body and "shows as failed" in body
        assert "only a warning" not in body
        from carter.install import prereqs

        assert "never fails" in (prereqs.check_credentials.__doc__ or "").lower()

    def test_the_documented_entry_is_what_the_package_ships(self) -> None:
        shipped = json.loads((REPO / "mcp/opencode/github.json").read_text())
        env = shipped["carter-github"]["environment"]["GITHUB_PERSONAL_ACCESS_TOKEN"]
        assert env in self.doc()

    def test_the_token_is_a_file_not_an_environment_variable(self) -> None:
        assert "not** an environment variable" in self.doc()

    @pytest.mark.parametrize("sub", ["set", "check"])
    def test_the_token_commands_take_no_options_but_verbose(self, sub: str) -> None:
        assert help_options("github-token", sub) <= {"--verbose"}

    def test_set_reads_the_token_from_stdin_only(self) -> None:
        block = norm(section(text("reference/cli.md"), "carter github-token set", "###"))
        assert "standard input" in block and "takes no arguments" in block
        assert "`E-PAT-TYPE`" in block and "0600" in block and "0700" in block

    def test_check_documents_the_write_probe_and_the_selection_limit(self) -> None:
        block = norm(section(text("reference/cli.md"), "carter github-token check", "###"))
        assert "all-zero commit" in block and "Resource not accessible" in block
        assert "All repositories" in block and "14 days" in block and "E-PAT-PERM" in block
        assert "agents can open PRs" in block and "Pull requests: write" in block
        assert "on a repository you own" in block and "its name is never printed" in block

    def test_probe_repo_is_in_the_schema_and_the_configuration_doc(self) -> None:
        assert Github().probe_repo == ""
        assert "probe_repo" in text("reference/configuration.md")
