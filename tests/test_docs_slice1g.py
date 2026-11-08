"""User docs for the parts of slice 1G that exist (plan 003 step 24, partial).

Checked against the code like ``test_docs_slice1.py``: documented options equal ``--help``,
the consent groups equal ``g2_rules.json``, the TOML example loads, and the interim shape is
stated plainly. Pending with the github-token / push / pr steps: their commands, the A+ flow
in ``write-operations.md``, the PAT guide in ``mcp-servers.md`` and the no-``export
GITHUB_TOKEN`` rule.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.identity.policyset import consent_groups

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"


def text(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8")


def section(doc: str, heading: str, level: str = "##") -> str:
    start = doc.index(f"\n{level} {heading}\n")
    rest = doc[start + 1 :]
    nxt = re.search(rf"\n#{{1,{len(level)}}} ", rest[5:])  # next heading of the same or higher rank
    return rest if not nxt else rest[: nxt.start() + 5]


def help_options(*command: str) -> set[str]:
    out = CliRunner().invoke(main, [*command, "--help"]).output
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", out)) - {"--help", "--base-dir"}


def documented(block: str) -> set[str]:
    return set(re.findall(r"`(?:-\w, )?(--[a-z][a-z0-9-]+)", block)) - {"--help", "--base-dir"}


class TestCliReference:
    @pytest.mark.parametrize("sub", ["install", "remove"])
    def test_guard_options_equal_help(self, sub: str) -> None:
        block = section(text("reference/cli.md"), f"carter guard {sub}", "###")
        assert documented(block) == help_options("guard", sub), sub

    def test_guard_status_has_only_the_reset_b_option(self) -> None:
        """Slice B (plan 007 step 14): `--reset-b` clears the rejection counters."""
        assert help_options("guard", "status") == {"--reset-b", "--verbose"}
        block = section(text("reference/cli.md"), "carter guard status", "###")
        assert "carter guard status [--reset-b] [-v]" in block
        assert documented(block) == {"--reset-b", "--verbose"}

    def test_every_guard_command_is_listed(self) -> None:
        out = CliRunner().invoke(main, ["guard", "--help"]).output
        doc = text("reference/cli.md")
        for cmd in ("install", "status", "remove"):
            assert cmd in out and f"### carter guard {cmd}" in doc

    def test_check_host_is_documented_as_read_only_and_names_only(self) -> None:
        assert "--host" in help_options("check")
        block = " ".join(section(text("reference/cli.md"), "carter check --host", "###").split())
        assert "never writes" in block and "never prints environment values" in block
        assert "plugin not installed" in block and "g2 rev 2 pending" in block

    def test_uninstall_and_install_flags_equal_help(self) -> None:
        doc = text("reference/cli.md")
        assert documented(section(doc, "carter uninstall")) == help_options("uninstall")
        assert documented(section(doc, "carter install")) == help_options("install")

    def test_check_probe_is_registered_and_documented_since_2a(self) -> None:
        assert "--probe" in help_options("check")
        doc = text("reference/cli.md")
        assert "### carter check --probe" in doc and "E-PROBE-SCOPE" in doc


class TestInstallGuide:
    def test_the_consent_groups_listed_are_the_live_ones_in_the_data_file(self) -> None:
        guards = section(text("guides/install.md"), "Guards")
        listed = set(re.findall(r"^\| `([a-z0-9_-]+)` \|", guards, flags=re.M))
        live = {g.id for g in consent_groups() if g.live}
        assert listed == live

    def test_it_explains_yes_non_tty_dry_run_remove_and_restart(self) -> None:
        guards = " ".join(section(text("guides/install.md"), "Guards").split())
        for needle in (
            "carter install --yes",
            "skipped with a notice",
            "carter guard install --dry-run",
            "carter guard remove",
            "Restart the OpenCode server",
            "--print-policies",
            "carter uninstall --keep-guards",
            "read-only token file and `~/.carter/state/audit/` stay",
        ):
            assert needle in guards, needle

    def test_the_interim_paragraph_is_honest(self) -> None:
        # plan 004 step 35: the 1G interim paragraph became the plugin section; the speed-bump
        # wording now lives in write-operations.md (the state before the plugin is confirmed)
        guards = " ".join(section(text("guides/install.md"), "Guards").split())
        assert "speed bump, not a boundary" in guards and "The plugin" in guards
        assert "never upgraded silently" in guards

    def test_the_restore_story_is_told(self) -> None:
        guards = " ".join(section(text("guides/install.md"), "Guards").split())
        assert "restores the backup" in guards


class TestConfigurationReference:
    def test_the_d52_example_loads_through_the_schema(self, tmp_path: Path) -> None:
        from carter.identity import load_identity

        doc = section(text("reference/configuration.md"), "User config: `~/.carter/config.toml`")
        block = next(
            b
            for b in re.findall(r"```toml\n(.*?)```", doc, flags=re.S)
            if "allow_project_opencode_edit" in b
        )
        data = tomllib.loads(block)
        (path,) = data["workspaces"]
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("schema = 2\n" + block.replace("/abs/path/to/project", str(tmp_path)))
        loaded = load_identity(cfg_file)
        assert loaded.workspaces[str(tmp_path)].allow_project_opencode_edit is True
        assert path.startswith("/abs")

    def test_it_says_only_a_human_run_apply_turns_it_into_policy(self) -> None:
        doc = " ".join(text("reference/configuration.md").split())
        assert "only when a human runs `carter guard install` or `carter update`" in doc


class TestFilesAndPaths:
    @pytest.mark.parametrize(
        "needle",
        [
            "~/.carter/guard-state.json",
            "~/.carter/backups/<timestamp>/opencode.json[c]",
            "~/.carter/gitconfig",
            "~/.carter/secrets/gh-read.token",
            "~/.carter/state/audit/",
            ".carter/state/handoff/<branch>.md",
        ],
    )
    def test_each_new_path_is_listed(self, needle: str) -> None:
        assert needle in text("reference/files-and-paths.md")

    def test_the_handoff_dir_is_said_to_be_outside_state_snapshots(self) -> None:
        doc = " ".join(text("reference/files-and-paths.md").split())
        assert "Never part of the `.carter/.git` snapshots" in doc

    def test_guard_state_is_0600_and_survives_older_installers(self) -> None:
        row = next(
            ln
            for ln in text("reference/files-and-paths.md").splitlines()
            if ln.startswith("| `~/.carter/guard-state.json`")
        )
        assert "0600" in row and "older installer" in row and "never rebuilt" in row


class TestTroubleshooting:
    @pytest.mark.parametrize(
        "needle",
        [
            "E-POLICIES-MISSING", "E-HUMAN-TERMINAL", "E-STATE-INVALID",
            "Blocked by configuration policy", "opencode.json[c]", "bad config line",
        ],
    )  # fmt: skip
    def test_each_guard_symptom_has_a_row(self, needle: str) -> None:
        assert needle in section(text("troubleshooting.md"), "Guards") or needle in text(
            "troubleshooting.md"
        )

    def test_no_row_still_tells_the_user_devops_pushes(self) -> None:
        assert "Ask Maestro to hand the push to carter-devops" not in text("troubleshooting.md")


# ── Plan 003 step 24, second half: github-token, push, pr, the A+ flow, the PAT guide ────────


def all_user_docs() -> dict[str, str]:
    """README and every doc a user reads (history lives in docs/rfcs and docs/adr)."""
    found = {"README.md": (REPO / "README.md").read_text(encoding="utf-8")}
    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS).as_posix()
        if not rel.startswith(("rfcs/", "adr/")):
            found[f"docs/{rel}"] = path.read_text(encoding="utf-8")
    return found


class TestNewCommandsInTheCliReference:
    def test_push_options_equal_help(self) -> None:
        block = section(text("reference/cli.md"), "carter push")
        expected = {"--dry-run", "--set-upstream", "--verbose"}
        assert documented(block) == help_options("push") == expected

    @pytest.mark.parametrize(
        "command", [["pr"], ["github-token", "set"], ["github-token", "check"]]
    )
    def test_commands_without_options_say_so(self, command: list[str]) -> None:
        assert help_options(*command) <= {"--verbose"}  # nothing but -v (D68 a)

    def test_every_new_command_is_in_the_table_and_has_a_heading(self) -> None:
        doc = text("reference/cli.md")
        for name in ("github-token", "push", "pr"):
            assert f"[`{name}`](#carter-{name})" in doc
            assert f"\n## carter {name}\n" in doc
        for sub in ("set", "check"):
            assert f"### carter github-token {sub}" in doc
        out = CliRunner().invoke(main, ["--help"]).output
        for name in ("github-token", "push", "pr"):
            assert name in out

    def test_push_and_pr_are_documented_for_a_human_in_the_terminal_or_the_bang_shell(
        self,
    ) -> None:
        doc = " ".join(text("reference/cli.md").split())
        assert doc.count("For a human only") >= 2  # D68 g
        assert "`!carter push`" in doc and "no terminal is needed" in doc
        assert "asks nothing" in doc

    def test_github_token_set_takes_the_token_from_stdin_only(self) -> None:
        block = " ".join(
            section(text("reference/cli.md"), "carter github-token set", "###").split()
        )
        assert "standard input" in block and "takes no arguments" in block
        assert "`E-PAT-TYPE`" in block and "0600" in block and "0700" in block

    def test_github_token_check_documents_the_write_probe_and_the_selection_limit(self) -> None:
        block = " ".join(
            section(text("reference/cli.md"), "carter github-token check", "###").split()
        )
        assert "all-zero commit" in block and "Resource not accessible" in block
        assert "All repositories" in block and "14 days" in block and "E-PAT-PERM" in block

    def test_check_host_lists_the_token_items(self) -> None:
        block = " ".join(section(text("reference/cli.md"), "carter check --host", "###").split())
        assert "read-only GitHub token" in block and "cannot write" in block


class TestConfigurationGithubTable:
    def test_read_token_file_example_equals_the_schema_default(self, tmp_path: Path) -> None:
        from carter.identity import load_identity
        from carter.identity.schema import Github

        doc = section(text("reference/configuration.md"), "User config: `~/.carter/config.toml`")
        block = next(
            b for b in re.findall(r"```toml\n(.*?)```", doc, flags=re.S) if "[github]" in b
        )
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(block.replace("/abs/path", str(tmp_path)))
        assert load_identity(cfg_file).github == Github()
        assert "`read_token_file`" in doc and "never the token itself" in doc


class TestWriteOperationsAPlusFlow:
    def doc(self) -> str:
        raw = re.sub(r"^> ?", "", text("guides/write-operations.md"), flags=re.M)
        return " ".join(raw.split())

    def test_the_flow_is_handoff_then_push_then_pr(self) -> None:
        doc = self.doc()
        i_hand = doc.index("The agent writes the handoff")
        i_push = doc.index("You run `carter push`")
        i_pr = doc.index("You run `carter pr`")
        assert i_hand < i_push < i_pr
        for needle in (
            ".carter/state/handoff/<encoded-branch>.md",
            "`feat/x` becomes `feat%2Fx.md`",
            "Only these five keys are accepted",
            "carter push --dry-run",
            "the default branch too: nothing to type",
            "deleted only after the pull request exists",
            "There are no options for forcing",
        ):
            assert needle in doc, needle

    def test_the_example_handoff_parses(self) -> None:
        import textwrap

        from carter.aplus.handoff import parse_handoff

        raw = text("guides/write-operations.md")
        block = re.search(r"\n\s*```markdown\n(.*?)\n\s*```", raw, flags=re.S)
        assert block
        item, _ = parse_handoff(textwrap.dedent(block.group(1)) + "\n")
        assert item.base == "main" and item.repo == "owner/name" and item.draft is False
        assert item.title == "feat(auth): add token refresh" and "## Summary" in item.body

    def test_it_says_they_are_for_the_human_in_a_terminal_or_the_tagged_bang_shell(self) -> None:
        doc = self.doc()
        assert "They are for you, not an agent" in doc and "`!carter push`" in doc
        assert "once the plugin has tagged it" in doc  # D68 g

    def test_the_typed_bang_fallback_is_unvalidated_and_must_be_typed(self) -> None:
        doc = self.doc()
        assert "unvalidated fallback" in doc
        assert "Type such lines yourself; never paste a line that starts with `!`" in doc
        assert "a pasted one is sent to the model" in doc

    def test_issues_comments_and_releases_have_no_agent_path(self) -> None:
        doc = self.doc()
        assert "no agent path for issues, comments, reviews or releases" in doc

    def test_the_interim_paragraph_is_here_and_in_install(self) -> None:
        wo = " ".join(text("guides/write-operations.md").split())
        assert "speed bump" in wo and "plugin" in wo and "isolation" in wo
        assert "stored but not injected into agent shells" in wo
        assert "Agent commits still use your own git config" in wo
        install = " ".join(text("guides/install.md").split())
        assert "speed bump" in install and "plugin" in install and "isolation" in install


class TestMcpServersGithubToken:
    def doc(self) -> str:
        return " ".join(text("guides/mcp-servers.md").split())

    def test_the_token_guide_follows_the_contract(self) -> None:
        doc = self.doc()
        for needle in (
            "fine-grained personal access token",
            "Classic tokens (`ghp_`)",
            '"All repositories" is accepted but wider than needed',
            "never to another organisation's",
            "`[github] probe_repo",
            "the repository's name is never printed",
            "Metadata, Contents, Pull requests, Issues, Actions, Checks and Commit statuses",
            "90 days or less",
            "SAML single sign-on",
            "`carter github-token set`",
            "`carter github-token check`",
            "~/.carter/secrets/gh-read.token",
            "{file:~/.carter/secrets/gh-read.token}",
            "directory 0700, file 0600",
            "Treat it as disclosed to your model provider",
        ):
            assert needle in doc, needle

    def test_the_documented_entry_is_what_the_package_ships(self) -> None:
        import json

        shipped = json.loads((REPO / "mcp/opencode/github.json").read_text())
        env = shipped["carter-github"]["environment"]["GITHUB_PERSONAL_ACCESS_TOKEN"]
        assert env in self.doc()

    def test_install_no_longer_asks_for_an_exported_github_token(self) -> None:
        doc = self.doc()
        assert "GitHub read-only token not found" in doc
        assert "not** an environment variable" in doc


class TestNoStaleAdvice:
    def test_no_doc_recommends_exporting_github_token(self) -> None:
        offenders = [
            name
            for name, body in all_user_docs().items()
            if re.search(r"export\s+(?:GH|GITHUB)_TOKEN", body)
        ]
        assert offenders == []

    def test_no_doc_describes_devops_pushing(self) -> None:
        patterns = (
            r"only (?:the )?devops (?:agent )?(?:can|may|is allowed to) (?:push|run)",
            r"only devops can push",
            r"the only agent that pushes",
            r"devops only\b",
            r"handed to devops",
            r"hand(?:s|ed)? (?:the )?(?:push )?(?:over )?to devops",
            r"devops (?:then )?(?:pushes|runs `?git push)",
            r"reserved for devops",
        )
        hits = []
        for name, body in all_user_docs().items():
            flat = " ".join(body.split()).lower()
            hits += [(name, p) for p in patterns if re.search(p, flat)]
        # "Pushing, publishing ... reserved for DevOps" is allowed only for Jira/Slack/Vault.
        assert [h for h in hits if h[1] != r"reserved for devops"] == []
        for name, body in all_user_docs().items():
            for match in re.finditer(
                r"[^.]*reserved for devops[^.]*\.", " ".join(body.split()), re.I
            ):
                clause = match.group(0).lower().split(";")[-1]
                assert "push" not in clause, (name, match.group(0))

    def test_the_safety_page_says_nobody_pushes(self) -> None:
        doc = " ".join(text("guides/safety-and-permissions.md").split())
        assert "**Nobody pushes.**" in doc and "DevOps included" in doc

    def test_the_readme_says_you_push(self) -> None:
        readme = " ".join((REPO / "README.md").read_text(encoding="utf-8").split())
        assert "No agent pushes: you do, with `carter push`" in readme


class TestTroubleshootingHandoffRows:
    @pytest.mark.parametrize(
        "code",
        ["E-HANDOFF", "E-SECRET-SCAN", "E-B-UNSIGNED", "E-APLUS-ARGS", "E-PAT-TYPE", "E-PAT-PERM"],
    )
    def test_each_code_has_a_row(self, code: str) -> None:
        assert f"`{code}`" in section(text("troubleshooting.md"), "Guards")

    def test_every_documented_code_exists_in_the_registry(self) -> None:
        from carter.identity.errors import registry

        for code in set(re.findall(r"\| `(E-[A-Z0-9-]+)`", text("troubleshooting.md"))):
            assert code in registry(), code


class TestProbeRepositoryDocs:
    def test_cli_reference_describes_the_owned_repository_probe(self) -> None:
        block = " ".join(
            section(text("reference/cli.md"), "carter github-token check", "###").split()
        )
        assert "on a repository you own" in block and "its name is never printed" in block
        assert "skipped (INFO)" in block and "prefers a narrow selection" in block
        assert "keep the selection narrow" not in block

    def test_the_guides_never_say_all_repositories_is_forbidden(self) -> None:
        for name, body in all_user_docs().items():
            flat = " ".join(body.split())
            assert 'Never "All repositories"' not in flat, name
            assert "never 'All repositories'" not in flat, name

    def test_probe_repo_is_in_the_configuration_example_and_the_schema(self) -> None:
        from carter.identity.schema import Github

        assert Github().probe_repo == ""
        assert "probe_repo" in text("reference/configuration.md")
