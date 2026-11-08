# ruff: noqa: E501
"""User docs for slice CI-E, review-only CI (plan 008 step 7): the guide covers the workflow, the
docs equal the code (codes, rules, constants, options) and nothing teaches a bypass."""

from __future__ import annotations

import re

import click

from carter.ci import ENVIRONMENT, OPENCODE_VERSION, SECRET, WORKFLOW_REL, check, review, template
from carter.cli import main
from carter.identity import mode
from carter.identity.errors import E_CI_REVIEW, registry
from test_docs_slice1g import documented, section, text

GUIDE = "guides/ci-review.md"


def guide() -> str:
    return " ".join(text(GUIDE).split())


def help_of(*path: str) -> set[str]:
    group: click.Command = main
    for name in path:
        group = group.commands[name]  # type: ignore[attr-defined]
    return {o for p in group.params for o in getattr(p, "opts", ()) if o.startswith("--")} - {
        "--help"
    }


class TestGuide:
    def test_it_covers_what_the_plan_requires(self) -> None:
        body = guide()
        for needle in (
            "CI context E: review only", "makes no commits", "contents: read",
            "carter ci install review --dry-run", "refuses in an agent shell",
            WORKFLOW_REL, f"environment** `{ENVIRONMENT}`",
            f"secret** `{SECRET}`", "CODEOWNERS", "skipped, not failed", "`pull_request` only",
            "pull_request_target", "pinned to a commit SHA", "timeout-minutes", "cancel-in-progress",
            "$GITHUB_STEP_SUMMARY", "pull-requests: write", "this widens the scope",
            "E-CI-REVIEW", "CARTER_IDENTITY_MODE", "contexts C and D", "not built",
            "by **version**, not by hash", "spending limit", "carter ci check",
        ):  # fmt: skip
            assert needle in body, needle

    def test_every_code_it_names_is_registered(self) -> None:
        for code in set(re.findall(r"E-[A-Z0-9]+(?:-[A-Z0-9]+)+", text(GUIDE))):
            assert code in registry(), code

    def test_it_never_recommends_pull_request_target_or_a_wider_scope_without_saying_so(
        self,
    ) -> None:
        for sentence in re.findall(r"[^.]*pull_request_target[^.]*\.", guide()):
            assert re.search(r"\b(never|not|would)\b", sentence), sentence

    def test_the_numbers_are_the_code_s(self) -> None:
        body = guide()
        assert "15 minutes" in body and template.render().count("timeout-minutes: 15") == 1
        assert OPENCODE_VERSION  # pinned in the workflow, not in the prose
        assert set(review.ALLOWED_ACTIONS) == {"read", "glob", "grep"}
        for action in review.ALLOWED_ACTIONS:
            assert f"`{action}`" in body

    def test_the_modes_match_the_resolver(self) -> None:
        body = guide()
        for value in mode.MODES:
            assert f"`{value}`" in body
        for value in ("commit", "scheduled"):
            assert value in mode.UNBUILT and f"`{value}`" in body

    def test_no_link_into_the_local_only_folders(self) -> None:
        for target in re.findall(r"\]\(([^)]+)\)", text(GUIDE)):
            assert not target.startswith(("../adr", "../rfcs", "docs/adr", "docs/rfcs")), target

    def test_every_rule_id_the_docs_mention_exists_in_the_checker(self) -> None:
        mentioned = set(re.findall(r"CI\d{3}", text("troubleshooting.md")))
        source = check.__doc__ or ""
        assert mentioned and all(rule in source for rule in mentioned)


class TestReferenceEqualsCode:
    def test_the_install_options_are_documented_exactly(self) -> None:
        block = section(text("reference/cli.md"), "carter ci install", "###")
        assert (
            documented(block)
            == help_of("ci", "install")
            == {"--comment", "--dry-run", "--force", "--verbose"}
        )

    def test_the_review_options_are_documented_exactly(self) -> None:
        block = section(text("reference/cli.md"), "carter ci review", "###")
        assert documented(block) == help_of("ci", "review") == {"--comment"}

    def test_check_is_documented(self) -> None:
        assert "carter ci check FILE" in text("reference/cli.md")
        assert help_of("ci", "check") == set()

    def test_the_variables_the_driver_reads_are_all_documented(self) -> None:
        body = text("reference/cli.md")
        for name in (
            review.ENV_BASE_SHA,
            review.ENV_KEY_ENV,
            review.ENV_MODEL,
            review.ENV_COMMENT_FILE,
            review.ENV_SUMMARY,
            review.ENV_EVENT,
            SECRET,
        ):
            assert name in body, name

    def test_the_emit_table_has_the_mode_key(self) -> None:
        assert "| `mode` |" in section(text("reference/cli.md"), "carter ops config --emit", "###")

    def test_the_file_is_listed_and_the_config_key_documented(self) -> None:
        assert "carter-review.yml" in text("reference/files-and-paths.md")
        assert "CARTER_IDENTITY_MODE" in text("reference/configuration.md")

    def test_troubleshooting_has_the_code_and_the_surprising_ci_variable(self) -> None:
        body = text("troubleshooting.md")
        assert E_CI_REVIEW in body and "unset CI GITHUB_ACTIONS" in body

    def test_the_safety_guide_and_index_link_the_guide(self) -> None:
        assert "ci-review.md" in text("guides/safety-and-permissions.md")
        assert "guides/ci-review.md" in text("README.md")
